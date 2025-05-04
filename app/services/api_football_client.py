# app/services/api_football_client.py
import requests
import json
import logging
from datetime import datetime, timedelta
import time
import random
import threading
import queue
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from flask import current_app
from app import db
from app.models.scheduled_task import ScheduledTask
from app.models.api_request_log import APIRequestLog
from app.models.api_quota import APIQuota

logger = logging.getLogger(__name__)

class APIFootballClient:
    """
    Client pour l'API Football (api-football.com)
    
    Cette classe gère :
    - Les appels à l'API
    - Le suivi des quotas
    - La planification des requêtes
    """
    
    BASE_URL = "https://v3.football.api-sports.io"
    
    def __init__(self, app=None):
        self.app = app
        self.api_key = None
        self.host = "api-football-v1.p.rapidapi.com"
        self.daily_limit = 100  # Limite quotidienne du plan gratuit
        self.requests_queue = queue.Queue()
        self.scheduler = None
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialise le client avec l'application Flask"""
        self.app = app
        self.api_key = app.config['API_FOOTBALL_KEY']
        
        # Afficher la clé API pour le débogage (temporaire)
        print(f"DEBUG - API Key: {self.api_key}")
        
        # Configurer le scheduler avec stockage dans la base de données
        jobstores = {
            'default': SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI'])
        }
        self.scheduler = BackgroundScheduler(jobstores=jobstores)
        self.scheduler.start()
        
        # Restaurer les tâches planifiées depuis la base de données
        try:
            self._restore_scheduled_tasks()
        except Exception as e:
            logger.error(f"Erreur lors de la restauration des tâches planifiées: {str(e)}")
        
        # Démarrer le worker de traitement de la file d'attente
        self._start_queue_worker()
        
        logger.info("API Football Client initialisé avec succès")
    
    def _get_headers(self):
        """Retourne les en-têtes pour les requêtes API"""
        headers = {
            'X-RapidAPI-Key': self.api_key,
            'X-RapidAPI-Host': self.host
        }
        return headers
    
    def _make_request(self, endpoint, params=None):
        """
        Effectue une requête à l'API
        
        Args:
            endpoint: L'endpoint de l'API (ex: /leagues)
            params: Paramètres de la requête (optionnel)
            
        Returns:
            Les données de la réponse ou None en cas d'erreur
        """
        url = f"{self.BASE_URL}/{endpoint}"
        
        try:
            # Afficher les détails de la requête pour débogage
            headers = self._get_headers()
            print(f"DEBUG - API Request: URL={url}, Params={params}")
            
            response = requests.get(url, headers=headers, params=params)
            
            # Afficher la réponse pour débogage
            print(f"DEBUG - API Response: Status={response.status_code}, Text={response.text[:200]}...")
            
            # Enregistrer l'utilisation de l'API
            try:
                self._log_api_request(endpoint, response.status_code)
            except Exception as e:
                print(f"DEBUG - Logging error: {e}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Erreur API: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Exception lors de l'appel à l'API: {str(e)}")
            return None
    
    def _log_api_request(self, endpoint, status_code):
        """
        Enregistre l'utilisation de l'API dans la base de données
        
        Args:
            endpoint: L'endpoint appelé
            status_code: Code de statut HTTP de la réponse
        """
        try:
            with self.app.app_context():
                log = APIRequestLog(
                    endpoint=endpoint,
                    status_code=status_code,
                    timestamp=datetime.utcnow()
                )
                db.session.add(log)
                db.session.commit()
                
                # Mettre à jour également le quota quotidien
                today = datetime.utcnow().date()
                quota = APIQuota.query.filter_by(date=today).first()
                
                if quota:
                    quota.used += 1
                else:
                    quota = APIQuota(date=today, used=1, limit=self.daily_limit)
                    db.session.add(quota)
                
                db.session.commit()
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement de l'utilisation de l'API: {str(e)}")
    
    def get_remaining_requests(self):
        """
        Récupère le nombre de requêtes restantes pour la journée
        
        Returns:
            Le nombre de requêtes restantes
        """
        try:
            with self.app.app_context():
                today = datetime.utcnow().date()
                tomorrow = today + timedelta(days=1)
                
                # Compter les requêtes utilisées aujourd'hui
                requests_used = APIRequestLog.query.filter(
                    APIRequestLog.timestamp >= today,
                    APIRequestLog.timestamp < tomorrow
                ).count()
                
                return max(0, self.daily_limit - requests_used)
        except Exception as e:
            logger.error(f"Erreur lors du calcul des requêtes restantes: {str(e)}")
            return 0
    
    def schedule_task(self, task_type, endpoint, params=None, execution_time=None, recurrence=None, description=None):
        """
        Planifie une tâche pour exécution future
        
        Args:
            task_type: Type de tâche (import_teams, import_players, etc.)
            endpoint: Endpoint de l'API à appeler
            params: Paramètres de la requête (optionnel)
            execution_time: Date/heure d'exécution (datetime) ou None pour exécution immédiate
            recurrence: Expression cron pour les tâches récurrentes (optionnel)
            description: Description de la tâche (optionnel)
            
        Returns:
            L'ID de la tâche planifiée
        """
        try:
            with self.app.app_context():
                # Créer l'enregistrement de tâche dans la base de données
                task = ScheduledTask(
                    task_type=task_type,
                    endpoint=endpoint,
                    parameters=json.dumps(params) if params else None,
                    execution_time=execution_time,
                    recurrence=recurrence,
                    description=description,
                    status='PENDING'
                )
                db.session.add(task)
                db.session.commit()
                
                # Planifier la tâche
                if execution_time:
                    # Tâche planifiée pour une date/heure spécifique
                    if recurrence:
                        # Tâche récurrente
                        job = self.scheduler.add_job(
                            self._execute_task,
                            'cron',
                            args=[task.id],
                            start_date=execution_time,
                            **self._parse_cron_expression(recurrence),
                            id=f"task_{task.id}"
                        )
                    else:
                        # Tâche unique
                        job = self.scheduler.add_job(
                            self._execute_task,
                            'date',
                            args=[task.id],
                            run_date=execution_time,
                            id=f"task_{task.id}"
                        )
                else:
                    # Exécution immédiate - ajouter à la file d'attente
                    self.requests_queue.put(task.id)
                
                return task.id
        except Exception as e:
            logger.error(f"Erreur lors de la planification de la tâche: {str(e)}")
            return None
    
    def _parse_cron_expression(self, cron_expression):
        """
        Convertit une expression cron en paramètres pour APScheduler
        
        Args:
            cron_expression: Expression cron (ex: "0 0 * * *" pour tous les jours à minuit)
            
        Returns:
            Dictionnaire de paramètres pour APScheduler
        """
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError("Expression cron invalide")
        
        return {
            'minute': parts[0],
            'hour': parts[1],
            'day': parts[2],
            'month': parts[3],
            'day_of_week': parts[4]
        }
    
    def _restore_scheduled_tasks(self):
        """Restaure les tâches planifiées depuis la base de données"""
        try:
            with self.app.app_context():
                # Récupérer les tâches planifiées qui ne sont pas terminées
                tasks = ScheduledTask.query.filter(
                    ScheduledTask.status.in_(['PENDING', 'SCHEDULED']),
                    ScheduledTask.execution_time > datetime.utcnow()
                ).all()
                
                for task in tasks:
                    if task.recurrence:
                        # Tâche récurrente
                        self.scheduler.add_job(
                            self._execute_task,
                            'cron',
                            args=[task.id],
                            start_date=task.execution_time,
                            **self._parse_cron_expression(task.recurrence),
                            id=f"task_{task.id}"
                        )
                    else:
                        # Tâche unique
                        self.scheduler.add_job(
                            self._execute_task,
                            'date',
                            args=[task.id],
                            run_date=task.execution_time,
                            id=f"task_{task.id}"
                        )
        except Exception as e:
            logger.error(f"Erreur lors de la restauration des tâches planifiées: {str(e)}")
    
    def _start_queue_worker(self):
        """Démarre le worker de traitement de la file d'attente"""
        def worker():
            while True:
                try:
                    # Vérifier s'il reste des requêtes pour aujourd'hui
                    remaining = self.get_remaining_requests()
                    if remaining <= 0:
                        # Pas assez de requêtes restantes, attendre jusqu'à demain
                        now = datetime.utcnow()
                        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                        sleep_time = (tomorrow - now).total_seconds()
                        logger.info(f"Quota d'API épuisé, reprise demain. En attente pour {sleep_time} secondes.")
                        time.sleep(sleep_time)
                        continue
                    
                    # Récupérer une tâche de la file d'attente (avec timeout)
                    task_id = self.requests_queue.get(timeout=60)
                    
                    # Exécuter la tâche
                    self._execute_task(task_id)
                    
                    # Marquer la tâche comme terminée dans la file d'attente
                    self.requests_queue.task_done()
                    
                    # Attendre un peu entre chaque requête pour éviter de surcharger l'API
                    time.sleep(1)
                    
                except queue.Empty:
                    # Pas de tâche dans la file d'attente, continuer
                    continue
                except Exception as e:
                    logger.error(f"Erreur dans le worker de file d'attente: {str(e)}")
                    time.sleep(5)
        
        # Démarrer le worker dans un thread séparé
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
    
    def _execute_task(self, task_id):
        """
        Exécute une tâche planifiée
        
        Args:
            task_id: L'ID de la tâche à exécuter
        """
        try:
            with self.app.app_context():
                # Récupérer la tâche
                task = ScheduledTask.query.get(task_id)
                if not task:
                    logger.error(f"Tâche {task_id} non trouvée")
                    return
                
                # Mettre à jour le statut
                task.status = 'RUNNING'
                task.last_run = datetime.utcnow()
                db.session.commit()
                
                try:
                    # Extraire les paramètres
                    params = json.loads(task.parameters) if task.parameters else None
                    
                    # Effectuer la requête API
                    response = self._make_request(task.endpoint, params)
                    
                    # Traiter la réponse selon le type de tâche
                    if task.task_type == 'import_teams':
                        self._process_teams_data(response)
                    elif task.task_type == 'import_players':
                        self._process_players_data(response)
                    elif task.task_type == 'import_fixtures':
                        self._process_matches_data(response)
                    elif task.task_type == 'import_statistics':
                        self._process_statistics_data(response)
                    # Ajouter d'autres types de tâches au besoin
                    
                    # Mettre à jour le statut
                    task.status = 'COMPLETED'
                    task.result = json.dumps({'success': True})
                    db.session.commit()
                    
                except Exception as e:
                    logger.error(f"Erreur lors de l'exécution de la tâche {task_id}: {str(e)}")
                    
                    # Mettre à jour le statut avec l'erreur
                    task.status = 'ERROR'
                    task.result = json.dumps({'error': str(e)})
                    db.session.commit()
        
        except Exception as e:
            logger.error(f"Erreur lors du traitement de la tâche {task_id}: {str(e)}")
    
    # Méthodes de traitement des données
    
    def _process_teams_data(self, data):
        """
        Traite les données d'équipes et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données d'équipes invalides")
            return
        
        from app.models.club import Club
        
        for team_data in data['response']:
            if not isinstance(team_data, dict):
                logger.warning(f"Format de données d'équipe inattendu: {type(team_data)}")
                continue
                
            team = team_data.get('team', {})
            venue = team_data.get('venue', {})
            
            if not isinstance(team, dict) or not isinstance(venue, dict):
                logger.warning(f"Structure de données inattendue: team {type(team)}, venue {type(venue)}")
                continue
            
            # Créer ou mettre à jour l'équipe dans la base de données
            db_team = Club.query.filter_by(api_id=team.get('id')).first()
            
            if not db_team:
                db_team = Club(
                    api_id=team.get('id'),
                    name=team.get('name'),
                    short_name=team.get('code') or team.get('name')[:3].upper(),
                    tla=team.get('code'),
                    crest=team.get('logo'),
                    founded=team.get('founded'),
                    venue=venue.get('name'),
                    address=venue.get('address'),
                    website=team.get('website')
                )
                db.session.add(db_team)
            else:
                # Mettre à jour les informations existantes
                db_team.name = team.get('name')
                db_team.short_name = team.get('code') or team.get('name')[:3].upper()
                db_team.tla = team.get('code')
                db_team.crest = team.get('logo')
                db_team.founded = team.get('founded')
                db_team.venue = venue.get('name')
                db_team.address = venue.get('address')
                db_team.website = team.get('website')
            
        db.session.commit()
        logger.info(f"Importation de {len(data['response'])} équipes terminée")
    
    def _process_players_data(self, data):
        """
        Traite les données de joueurs et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données de joueurs invalides")
            return
        
        from app.models.player import Player
        from app.models.club import Club
        
        players_count = 0
        
        for player_data in data['response']:
            if not isinstance(player_data, dict):
                logger.warning(f"Format de données de joueur inattendu: {type(player_data)}")
                continue
                
            player = player_data.get('player', {})
            
            if not isinstance(player, dict):
                logger.warning(f"Structure de données de joueur inattendue: {type(player)}")
                continue
            
            # Vérifier les informations de l'équipe
            statistics = player_data.get('statistics', [])
            team_data = {}
            
            if statistics and isinstance(statistics, list) and len(statistics) > 0:
                team_data = statistics[0].get('team', {})
            
            if not team_data or not isinstance(team_data, dict):
                logger.warning(f"Données d'équipe manquantes ou invalides pour le joueur {player.get('name')}")
                continue
            
            # Trouver le club associé
            if team_data.get('id'):
                club = Club.query.filter_by(api_id=team_data.get('id')).first()
                club_id = club.id if club else None
            else:
                club_id = None
                logger.warning(f"ID d'équipe manquant pour le joueur {player.get('name')}")
            
            # Vérifier les informations de naissance
            birth_data = player.get('birth', {})
            date_of_birth = None
            
            if birth_data and isinstance(birth_data, dict) and birth_data.get('date'):
                try:
                    date_of_birth = datetime.strptime(birth_data.get('date'), '%Y-%m-%d')
                except Exception as e:
                    logger.warning(f"Format de date invalide pour le joueur {player.get('name')}: {e}")
            
            # Créer ou mettre à jour le joueur dans la base de données
            db_player = Player.query.filter_by(api_id=player.get('id')).first()
            
            if not db_player:
                db_player = Player(
                    api_id=player.get('id'),
                    name=player.get('name'),
                    first_name=player.get('firstname'),
                    last_name=player.get('lastname'),
                    date_of_birth=date_of_birth,
                    nationality=player.get('nationality'),
                    position=player.get('position'),
                    photo_url=player.get('photo'),
                    club_id=club_id
                )
                db.session.add(db_player)
                players_count += 1
            else:
                # Mettre à jour les informations existantes
                db_player.name = player.get('name')
                db_player.first_name = player.get('firstname')
                db_player.last_name = player.get('lastname')
                db_player.date_of_birth = date_of_birth
                db_player.nationality = player.get('nationality')
                db_player.position = player.get('position')
                db_player.photo_url = player.get('photo')
                if club_id:
                    db_player.club_id = club_id
                players_count += 1
        
        db.session.commit()
        logger.info(f"Importation de {players_count} joueurs terminée")
    
    def _process_matches_data(self, data):
        """
        Traite les données de matchs et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données de matchs invalides")
            return
        
        from app.models.match import Match
        from app.models.club import Club
        
        matches_count = 0
        
        for match_data in data['response']:
            if not isinstance(match_data, dict):
                logger.warning(f"Format de données de match inattendu: {type(match_data)}")
                continue
                
            fixture = match_data.get('fixture', {})
            league = match_data.get('league', {})
            teams = match_data.get('teams', {})
            goals = match_data.get('goals', {})
            score = match_data.get('score', {})
            
            if not all(isinstance(x, dict) for x in [fixture, league, teams, goals, score]):
                logger.warning("Structure de données de match inattendue")
                continue
            
            # Vérifier les équipes
            home_team_data = teams.get('home', {})
            away_team_data = teams.get('away', {})
            
            if not isinstance(home_team_data, dict) or not isinstance(away_team_data, dict):
                logger.warning("Données d'équipe invalides")
                continue
            
            # Trouver les équipes dans la base de données
            home_team = Club.query.filter_by(api_id=home_team_data.get('id')).first()
            away_team = Club.query.filter_by(api_id=away_team_data.get('id')).first()
            
            if not home_team or not away_team:
                # Créer les équipes si elles n'existent pas
                if not home_team:
                    home_team = Club(
                        api_id=home_team_data.get('id'),
                        name=home_team_data.get('name'),
                        short_name=home_team_data.get('name')[:3].upper(),
                        crest=home_team_data.get('logo')
                    )
                    db.session.add(home_team)
                    db.session.flush()  # Pour obtenir l'ID
                
                if not away_team:
                    away_team = Club(
                        api_id=away_team_data.get('id'),
                        name=away_team_data.get('name'),
                        short_name=away_team_data.get('name')[:3].upper(),
                        crest=away_team_data.get('logo')
                    )
                    db.session.add(away_team)
                    db.session.flush()  # Pour obtenir l'ID
            
            # Convertir la date du match
            match_date = datetime.utcnow()
            if fixture.get('date'):
                try:
                    match_date = datetime.strptime(fixture.get('date'), '%Y-%m-%dT%H:%M:%S%z')
                    # Convertir en UTC sans fuseau horaire
                    match_date = match_date.replace(tzinfo=None)
                except Exception as e:
                    logger.warning(f"Format de date invalide: {fixture.get('date')} - {e}")
            
            # Convertir le statut
            status_map = {
                'TBD': 'SCHEDULED',
                'NS': 'SCHEDULED',
                '1H': 'IN_PLAY',
                '2H': 'IN_PLAY',
                'HT': 'PAUSED',
                'ET': 'IN_PLAY',
                'P': 'PAUSED',
                'FT': 'FINISHED',
                'AET': 'FINISHED',
                'PEN': 'FINISHED',
                'BT': 'PAUSED',
                'SUSP': 'SUSPENDED',
                'INT': 'INTERRUPTED',
                'PST': 'POSTPONED',
                'CANC': 'CANCELLED',
                'ABD': 'ABANDONED',
                'AWD': 'AWARDED',
                'WO': 'WALKOVER'
            }
            
            status = status_map.get(fixture.get('status', {}).get('short'), 'UNKNOWN')
            
            # Récupérer les scores
            goals_home = goals.get('home')
            goals_away = goals.get('away')
            
            # Scores détaillés
            half_time = score.get('halftime', {})
            full_time = score.get('fulltime', {})
            extra_time = score.get('extratime', {})
            penalty = score.get('penalty', {})
            
            # Créer ou mettre à jour le match dans la base de données
            db_match = Match.query.filter_by(api_id=fixture.get('id')).first()
            
            if not db_match:
                db_match = Match(
                    api_id=fixture.get('id'),
                    competition=league.get('name'),
                    season=f"{league.get('season')}/{league.get('season')+1}" if league.get('season') else 'Inconnue',
                    matchday=league.get('round', '').replace('Regular Season - ', ''),
                    date=match_date,
                    status=status,
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    home_team_score=goals_home,
                    away_team_score=goals_away,
                    half_time_home=half_time.get('home'),
                    half_time_away=half_time.get('away'),
                    extra_time_home=extra_time.get('home'),
                    extra_time_away=extra_time.get('away'),
                    penalties_home=penalty.get('home'),
                    penalties_away=penalty.get('away')
                )
                db.session.add(db_match)
                matches_count += 1
            else:
                # Mettre à jour les informations existantes
                db_match.competition = league.get('name')
                db_match.season = f"{league.get('season')}/{league.get('season')+1}" if league.get('season') else 'Inconnue'
                db_match.matchday = league.get('round', '').replace('Regular Season - ', '')
                db_match.date = match_date
                db_match.status = status
                db_match.home_team_id = home_team.id
                db_match.away_team_id = away_team.id
                db_match.home_team_score = goals_home
                db_match.away_team_score = goals_away
                db_match.half_time_home = half_time.get('home')
                db_match.half_time_away = half_time.get('away')
                db_match.extra_time_home = extra_time.get('home')
                db_match.extra_time_away = extra_time.get('away')
                db_match.penalties_home = penalty.get('home')
                db_match.penalties_away = penalty.get('away')
                matches_count += 1
        
        db.session.commit()
        logger.info(f"Importation de {matches_count} matchs terminée")
    
    def _process_statistics_data(self, data):
        """
        Traite les données de statistiques et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données de statistiques invalides")
            return
        
        # Vérifier si nous avons des statistiques d'équipe ou de joueurs
        response = data['response']
        
        # Cas 1: Statistiques d'équipe (endpoint: teams/statistics)
        if isinstance(response, dict) and 'league' in response:
            # Traitement des statistiques d'équipe
            self._process_team_statistics(response)
            return
                
        # Cas 2: Statistiques de joueurs (endpoint: players)
        from app.models.player_stats import PlayerStats
        from app.models.player import Player
        
        players_count = 0
        
        for player_data in response:
            # Vérification que les données ont la structure attendue
            if not isinstance(player_data, dict):
                logger.warning(f"Format de données de joueur inattendu: {type(player_data)}")
                continue
                
            if 'player' not in player_data or 'statistics' not in player_data:
                logger.warning("Données de joueur incomplètes, manque 'player' ou 'statistics'")
                continue
                
            player = player_data['player']
            statistics = player_data.get('statistics', [])
            
            if not isinstance(player, dict) or not isinstance(statistics, list):
                logger.warning(f"Structure de données inattendue: player {type(player)}, statistics {type(statistics)}")
                continue
            
            # Rechercher le joueur associé
            db_player = Player.query.filter_by(api_id=player.get('id')).first()
            
            if not db_player:
                logger.warning(f"Joueur {player.get('id')} ({player.get('name')}) non trouvé")
                continue
            
            for stat in statistics:
                if not isinstance(stat, dict):
                    logger.warning(f"Format de statistiques inattendu: {type(stat)}")
                    continue
                    
                league = stat.get('league', {})
                if not isinstance(league, dict):
                    logger.warning(f"Format de ligue inattendu: {type(league)}")
                    continue
                    
                season = str(league.get('season', ''))
                if season:
                    # Formater la saison (par exemple "2023" devient "2023/2024")
                    try:
                        season_year = int(season)
                        season = f"{season_year}/{season_year+1}"
                    except ValueError:
                        # Si la conversion échoue, garder le format original
                        pass
                else:
                    logger.warning(f"Saison manquante pour les statistiques du joueur {db_player.id}")
                    continue
                
                # Créer ou mettre à jour les statistiques
                db_stats = PlayerStats.query.filter_by(
                    player_id=db_player.id,
                    season=season
                ).first()
                
                if not db_stats:
                    db_stats = PlayerStats(player_id=db_player.id, season=season)
                    db.session.add(db_stats)
                
                # Mise à jour des statistiques
                self._update_player_stats_from_api(db_stats, stat)
                players_count += 1
        
        db.session.commit()
        logger.info(f"Importation des statistiques terminée pour {players_count} joueurs")
    
    def _process_team_statistics(self, team_stats):
        """
        Traite les statistiques d'équipe
        
        Args:
            team_stats: Les statistiques d'équipe
        """
        try:
            if not isinstance(team_stats, dict):
                logger.warning(f"Format de données d'équipe inattendu: {type(team_stats)}")
                return
            
            # Récupérer les informations de base
            league = team_stats.get('league', {})
            team = team_stats.get('team', {})
            
            if not isinstance(league, dict):
                logger.warning(f"Format de données league inattendu: {type(league)}")
                return
                
            if not isinstance(team, dict):
                logger.warning(f"Format de données team inattendu: {type(team)}")
                return
            
            season = str(league.get('season', ''))
            team_id = team.get('id')
            
            if not team_id:
                logger.warning("ID d'équipe manquant dans les données")
                return
                
            logger.info(f"Traitement des statistiques de l'équipe {team.get('name')} pour la saison {season}")
            
            # Vérifier si l'équipe existe dans la base de données
            from app.models.club import Club
            from app.models.team_stats import TeamStats
            from app import db
            from datetime import datetime
            
            with db.session.begin_nested():  # Utiliser une transaction pour pouvoir faire rollback
                db_team = Club.query.filter_by(api_id=team_id).first()
                
                if not db_team:
                    logger.warning(f"Équipe {team_id} non trouvée dans la base de données")
                    # Créer l'équipe
                    db_team = Club(
                        api_id=team_id,
                        name=team.get('name'),
                        short_name=team.get('name')[:3].upper(),
                        crest=team.get('logo')
                    )
                    db.session.add(db_team)
                    db.session.flush()  # Pour obtenir l'ID sans commit
                    logger.info(f"Équipe {team.get('name')} créée")
                
                # Formater la saison
                formatted_season = season
                if season:
                    try:
                        season_year = int(season)
                        formatted_season = f"{season_year}/{season_year+1}"
                    except ValueError:
                        formatted_season = season
                else:
                    formatted_season = "2023/2024"  # Saison par défaut
                
                # Vérifier si les statistiques existent déjà
                db_stats = TeamStats.query.filter_by(
                    club_id=db_team.id,
                    season=formatted_season
                ).first()
                
                if not db_stats:
                    # Créer un nouvel enregistrement de statistiques
                    db_stats = TeamStats(
                        club_id=db_team.id,
                        season=formatted_season,
                        matches_played=0,
                        wins=0,
                        draws=0,
                        losses=0,
                        goals_for=0,
                        goals_against=0,
                        clean_sheets=0,
                        yellow_cards=0,
                        red_cards=0,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.session.add(db_stats)
                    logger.info(f"Nouvel enregistrement de statistiques créé pour {team.get('name')}")
                
                # Statistiques générales - Matches
                fixtures = team_stats.get('fixtures', {})
                if isinstance(fixtures, dict):
                    played = fixtures.get('played', {})
                    wins = fixtures.get('wins', {})
                    draws = fixtures.get('draws', {})
                    loses = fixtures.get('loses', {})
                    
                    if isinstance(played, dict) and 'total' in played:
                        db_stats.matches_played = played['total'] or 0
                    
                    if isinstance(wins, dict) and 'total' in wins:
                        db_stats.wins = wins['total'] or 0
                    
                    if isinstance(draws, dict) and 'total' in draws:
                        db_stats.draws = draws['total'] or 0
                    
                    if isinstance(loses, dict) and 'total' in loses:
                        db_stats.losses = loses['total'] or 0
                
                # Buts
                goals = team_stats.get('goals', {})
                if isinstance(goals, dict):
                    # Buts pour
                    goals_for = goals.get('for', {})
                    if isinstance(goals_for, dict) and 'total' in goals_for:
                        total_for = goals_for['total']
                        if isinstance(total_for, dict) and 'total' in total_for:
                            db_stats.goals_for = total_for['total'] or 0
                    
                    # Buts contre
                    goals_against = goals.get('against', {})
                    if isinstance(goals_against, dict) and 'total' in goals_against:
                        total_against = goals_against['total']
                        if isinstance(total_against, dict) and 'total' in total_against:
                            db_stats.goals_against = total_against['total'] or 0
                
                # Clean sheets
                clean_sheet = team_stats.get('clean_sheet', {})
                if isinstance(clean_sheet, dict) and 'total' in clean_sheet:
                    db_stats.clean_sheets = clean_sheet['total'] or 0
                
                # Cartes
                cards = team_stats.get('cards', {})
                if isinstance(cards, dict):
                    # Compteur pour les cartes jaunes et rouges
                    yellow_count = 0
                    red_count = 0
                    
                    # Cartes jaunes
                    yellow = cards.get('yellow', {})
                    if isinstance(yellow, dict):
                        for time_range, data in yellow.items():
                            if isinstance(data, dict) and 'total' in data and data['total'] is not None:
                                yellow_count += data['total']
                    
                    # Cartes rouges
                    red = cards.get('red', {})
                    if isinstance(red, dict):
                        for time_range, data in red.items():
                            if isinstance(data, dict) and 'total' in data and data['total'] is not None:
                                red_count += data['total']
                    
                    db_stats.yellow_cards = yellow_count
                    db_stats.red_cards = red_count
                
                # Mise à jour timestamp
                db_stats.updated_at = datetime.utcnow()
            
            # Commit en dehors de la transaction imbriquée
            db.session.commit()
            logger.info(f"Statistiques de l'équipe {team.get('name')} mises à jour")
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors du traitement des statistiques d'équipe: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _update_player_stats_from_api(self, db_stats, api_stats):
        """
        Met à jour les statistiques d'un joueur à partir des données de l'API
        
        Args:
            db_stats: L'objet PlayerStats à mettre à jour
            api_stats: Les statistiques de l'API
        """
        try:
            # Mise à jour des statistiques de base
            games = api_stats.get('games', {})
            if isinstance(games, dict):
                db_stats.matches_played = games.get('appearences', 0) or 0
                db_stats.minutes_played = games.get('minutes', 0) or 0
            
            # Buts et passes décisives
            goals = api_stats.get('goals', {})
            if isinstance(goals, dict):
                db_stats.goals = goals.get('total', 0) or 0
                db_stats.assists = goals.get('assists', 0) or 0
            
            # Discipline
            cards = api_stats.get('cards', {})
            if isinstance(cards, dict):
                db_stats.yellow_cards = cards.get('yellow', 0) or 0
                db_stats.red_cards = cards.get('red', 0) or 0
            
            # Statistiques offensives
            shots = api_stats.get('shots', {})
            if isinstance(shots, dict):
                db_stats.shots = shots.get('total', 0) or 0
                db_stats.shots_on_target = shots.get('on', 0) or 0
            
            # Passes
            passes = api_stats.get('passes', {})
            if isinstance(passes, dict):
                db_stats.passes = passes.get('total', 0) or 0
                db_stats.key_passes = passes.get('key', 0) or 0
                
                accuracy = passes.get('accuracy')
                if accuracy is not None:
                    try:
                        # Convertir en nombre
                        if isinstance(accuracy, str):
                            accuracy = accuracy.replace('%', '')
                        accuracy_float = float(accuracy)
                        db_stats.pass_accuracy = accuracy_float
                        
                        # Calculer le nombre de passes réussies
                        total_passes = passes.get('total', 0) or 0
                        if total_passes > 0:
                            db_stats.passes_completed = int(total_passes * accuracy_float / 100)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Impossible de convertir la précision des passes: {accuracy} - {e}")
            
            # Statistiques défensives
            tackles = api_stats.get('tackles', {})
            if isinstance(tackles, dict):
                db_stats.tackles = tackles.get('total', 0) or 0
                db_stats.tackles_won = tackles.get('blocks', 0) or 0
                db_stats.interceptions = tackles.get('interceptions', 0) or 0
            
            blocks = api_stats.get('blocks', {})
            if isinstance(blocks, dict):
                db_stats.blocks = blocks.get('total', 0) or 0
            
            duels = api_stats.get('duels', {})
            if isinstance(duels, dict):
                db_stats.duels = duels.get('total', 0) or 0
                db_stats.duels_won = duels.get('won', 0) or 0
            
            # Statistiques pour les gardiens de but
            goalkeeper = api_stats.get('goalkeeper', {})
            if isinstance(goalkeeper, dict):
                db_stats.saves = goalkeeper.get('saves', 0) or 0
                db_stats.goals_conceded = goalkeeper.get('goals_conceded', 0) or 0
                db_stats.clean_sheets = goalkeeper.get('cleansheets', 0) or 0
                db_stats.penalties_saved = goalkeeper.get('penalty_saved', 0) or 0
            
            # Note globale
            rating_value = api_stats.get('rating')
            if rating_value:
                try:
                    db_stats.rating = float(rating_value)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Impossible de convertir la note: {rating_value} - {e}")
            
            # Date de mise à jour
            from datetime import datetime
            db_stats.updated_at = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour des statistiques de joueur: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    
    def get_leagues(self, country=None, season=None, current=None):
        """
        Récupère les ligues disponibles
        
        Args:
            country: Filtrer par pays (optionnel)
            season: Filtrer par saison (optionnel)
            current: Filtrer par ligues en cours (optionnel)
            
        Returns:
            Les données des ligues
        """
        params = {}
        if country:
            params['country'] = country
        if season:
            params['season'] = season
        if current is not None:
            params['current'] = 'true' if current else 'false'
        
        return self._make_request('leagues', params)
    
    def get_teams(self, league_id=None, season=None, country=None):
        """
        Récupère les équipes
        
        Args:
            league_id: ID de la ligue (optionnel)
            season: Saison (optionnel)
            country: Pays (optionnel)
            
        Returns:
            Les données des équipes
        """
        params = {}
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if country:
            params['country'] = country
        
        return self._make_request('teams', params)
    
    def get_team_info(self, team_id):
        """
        Récupère les informations détaillées d'une équipe
        
        Args:
            team_id: ID de l'équipe
            
        Returns:
            Les données de l'équipe
        """
        params = {'id': team_id}
        return self._make_request('teams', params)
    
    def get_players(self, team_id=None, league_id=None, season=None, page=None):
        """
        Récupère les joueurs d'une équipe ou d'une ligue
        
        Args:
            team_id: ID de l'équipe (optionnel)
            league_id: ID de la ligue (optionnel)
            season: Saison (optionnel)
            page: Numéro de page (optionnel)
            
        Returns:
            Les données des joueurs
        """
        params = {}
        if team_id:
            params['team'] = team_id
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if page:
            params['page'] = page
        
        return self._make_request('players', params)
    
    def get_player_info(self, player_id, season=None):
        """
        Récupère les informations détaillées d'un joueur
        
        Args:
            player_id: ID du joueur
            season: Saison (optionnel)
            
        Returns:
            Les données du joueur
        """
        params = {'id': player_id}
        if season:
            params['season'] = season
        
        return self._make_request('players', params)
    
    def get_fixtures(self, league_id=None, team_id=None, date=None, season=None, status=None):
        """
        Récupère les matchs
        
        Args:
            league_id: ID de la ligue (optionnel)
            team_id: ID de l'équipe (optionnel)
            date: Date des matchs (optionnel)
            season: Saison (optionnel)
            status: Statut des matchs (optionnel)
            
        Returns:
            Les données des matchs
        """
        params = {}
        if league_id:
            params['league'] = league_id
        if team_id:
            params['team'] = team_id
        if date:
            params['date'] = date
        if season:
            params['season'] = season
        if status:
            params['status'] = status
        
        return self._make_request('fixtures', params)
    
    def get_fixture_statistics(self, fixture_id, team_id=None):
        """
        Récupère les statistiques d'un match
        
        Args:
            fixture_id: ID du match
            team_id: ID de l'équipe (optionnel)
            
        Returns:
            Les données des statistiques
        """
        params = {'fixture': fixture_id}
        if team_id:
            params['team'] = team_id
        
        return self._make_request('fixtures/statistics', params)
    
    def get_team_statistics(self, team_id, league_id, season):
        """
        Récupère les statistiques d'une équipe dans une ligue
        
        Args:
            team_id: ID de l'équipe
            league_id: ID de la ligue
            season: Saison
            
        Returns:
            Les données des statistiques
        """
        params = {
            'team': team_id,
            'league': league_id,
            'season': season
        }
        
        return self._make_request('teams/statistics', params)
    
    def get_players_statistics(self, league_id, season, page=None):
        """
        Récupère les statistiques des joueurs d'une ligue
        
        Args:
            league_id: ID de la ligue
            season: Saison
            page: Numéro de page (optionnel)
            
        Returns:
            Les données des statistiques
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        if page:
            params['page'] = page
        
        return self._make_request('players', params)