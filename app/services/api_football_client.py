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
            logger.debug(f"API Request: URL={url}, Params={params}")
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            # Enregistrer l'utilisation de l'API
            try:
                self._log_api_request(endpoint, response.status_code)
            except Exception as e:
                logger.error(f"Logging error: {str(e)}")
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 204:
                logger.info(f"Aucun résultat pour l'endpoint {endpoint} avec les paramètres {params}")
                return {"results": 0, "response": []}
            else:
                logger.error(f"Erreur API: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.Timeout:
            logger.error(f"Timeout lors de l'appel à l'API pour l'endpoint {endpoint}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"Erreur de connexion lors de l'appel à l'API pour l'endpoint {endpoint}")
            return None
        except Exception as e:
            logger.error(f"Exception lors de l'appel à l'API: {str(e)}")
            return None
        
    def import_upcoming_fixtures(self, team_id=None, league_id=None, date_from=None, date_to=None):
        """
        Importe les matchs à venir pour une équipe ou une ligue
        
        Args:
            team_id: ID de l'équipe (optionnel)
            league_id: ID de la ligue (optionnel)
            date_from: Date de début (format YYYY-MM-DD) (optionnel)
            date_to: Date de fin (format YYYY-MM-DD) (optionnel)
            
        Returns:
            Nombre de matchs importés
        """
        from app.models.match import Match
        from app.models.club import Club
        
        try:
            with self.app.app_context():
                # Préparer les paramètres de requête
                params = {'status': 'NS'}  # Seulement les matchs non commencés
                
                if team_id:
                    params['team'] = team_id
                if league_id:
                    params['league'] = league_id
                if date_from:
                    params['from'] = date_from
                if date_to:
                    params['to'] = date_to
                    
                # Si aucune date n'est spécifiée, prendre les 30 prochains jours
                if not date_from and not date_to:
                    today = datetime.now().strftime('%Y-%m-%d')
                    next_month = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
                    params['from'] = today
                    params['to'] = next_month
                
                # Récupérer les matchs depuis l'API
                response = self._make_request('fixtures', params)
                
                if not response or 'response' not in response:
                    logger.error("Aucun match à venir trouvé")
                    return 0
                    
                fixtures_data = response['response']
                imported_count = 0
                
                for fixture in fixtures_data:
                    try:
                        fixture_id = fixture['fixture']['id']
                        
                        # Vérifier si le match existe déjà
                        match = Match.query.filter_by(api_id=fixture_id).first()
                        
                        # Récupérer ou créer les équipes
                        home_team_data = fixture['teams']['home']
                        away_team_data = fixture['teams']['away']
                        
                        home_team = Club.query.filter_by(api_id=home_team_data['id']).first()
                        if not home_team:
                            home_team = Club(
                                api_id=home_team_data['id'],
                                name=home_team_data['name'],
                                short_name=home_team_data['name'][:3].upper(),
                                crest=home_team_data.get('logo')
                            )
                            db.session.add(home_team)
                            db.session.flush()
                        
                        away_team = Club.query.filter_by(api_id=away_team_data['id']).first()
                        if not away_team:
                            away_team = Club(
                                api_id=away_team_data['id'],
                                name=away_team_data['name'],
                                short_name=away_team_data['name'][:3].upper(),
                                crest=away_team_data.get('logo')
                            )
                            db.session.add(away_team)
                            db.session.flush()
                        
                        # Convertir la date du match
                        match_date = None
                        if fixture['fixture'].get('date'):
                            try:
                                match_date = datetime.strptime(fixture['fixture']['date'], '%Y-%m-%dT%H:%M:%S%z')
                                match_date = match_date.replace(tzinfo=None)  # Supprimer le fuseau horaire
                            except Exception as e:
                                logger.warning(f"Format de date invalide: {fixture['fixture'].get('date')} - {e}")
                                continue
                        
                        # Créer ou mettre à jour le match
                        if not match:
                            match = Match(
                                api_id=fixture_id,
                                competition=fixture['league']['name'],
                                season=f"{fixture['league']['season']}/{fixture['league']['season']+1}",
                                matchday=fixture['league'].get('round', '').replace('Regular Season - ', ''),
                                date=match_date,
                                status='SCHEDULED',
                                home_team_id=home_team.id,
                                away_team_id=away_team.id
                            )
                            db.session.add(match)
                            imported_count += 1
                        else:
                            match.date = match_date
                            match.competition = fixture['league']['name']
                            match.season = f"{fixture['league']['season']}/{fixture['league']['season']+1}"
                            match.matchday = fixture['league'].get('round', '').replace('Regular Season - ', '')
                            match.home_team_id = home_team.id
                            match.away_team_id = away_team.id
                            match.status = 'SCHEDULED'
                    
                    except Exception as e:
                        logger.error(f"Erreur lors de l'importation du match {fixture.get('fixture', {}).get('id')}: {str(e)}")
                        continue
                
                db.session.commit()
                return imported_count
                
        except Exception as e:
            logger.error(f"Erreur lors de l'importation des matchs à venir: {str(e)}")
            db.session.rollback()
            return 0
    
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
                
                logger.info(f"Exécution de la tâche {task_id}: {task.description}")
                
                try:
                    # Extraire les paramètres
                    params = json.loads(task.parameters) if task.parameters else None
                    
                    # Effectuer la requête API
                    response = self._make_request(task.endpoint, params)
                    
                    # Vérifier s'il y a des erreurs
                    if response and 'errors' in response and response['errors']:
                        raise Exception(f"Erreur API: {response['errors']}")
                    
                    # Traiter la réponse selon le type de tâche
                    result = self._process_task_response(task, response)
                    
                    # Mettre à jour le statut
                    task.status = 'COMPLETED'
                    task.result = json.dumps({'success': True, 'data': result})
                    db.session.commit()
                    
                    logger.info(f"Tâche {task_id} terminée avec succès")
                    
                except Exception as e:
                    logger.error(f"Erreur lors de l'exécution de la tâche {task_id}: {str(e)}")
                    
                    # Mettre à jour le statut avec l'erreur
                    task.status = 'ERROR'
                    task.result = json.dumps({'error': str(e)})
                    db.session.commit()
            
        except Exception as e:
            logger.error(f"Erreur lors du traitement de la tâche {task_id}: {str(e)}")

    def _process_task_response(self, task, response):
        """
        Traite la réponse de l'API selon le type de tâche
        
        Args:
            task: L'objet ScheduledTask
            response: La réponse de l'API
                
        Returns:
            Le résultat du traitement
        """
        task_type = task.task_type
        
        # Vérifier si la réponse est valide
        if not response or 'response' not in response:
            raise Exception("Réponse API invalide ou vide")
        
        # Selon le type de tâche, appeler la fonction appropriée
        if task_type == 'import_teams':
            return self._process_teams_data(response)
        elif task_type == 'import_players':
            return self._process_players_data(response)
        elif task_type == 'import_fixtures':
            return self._process_matches_data(response)
        elif task_type == 'import_statistics':
            return self._process_statistics_data(response)
        else:
            # Pour les autres types, simplement retourner les résultats
            return {
                'count': len(response.get('response', [])),
                'status': 'success'
            }
    
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
        from app.models.player_stats import PlayerStats
        
        players_count = 0
        stats_count = 0
        
        # Afficher la structure des données pour le débogage
        logger.info(f"Structure des données: {json.dumps(data['response'][0] if data['response'] else {}, indent=2)}")
        
        for player_data in data['response']:
            # Validation des données
            if not isinstance(player_data, dict):
                logger.warning(f"Format de données de joueur inattendu: {type(player_data)}")
                continue
                    
            player = player_data.get('player', {})
            statistics = player_data.get('statistics', [])
            
            if not isinstance(player, dict) or not isinstance(statistics, list):
                logger.warning(f"Structure de données inattendue: player {type(player)}, statistics {type(statistics)}")
                continue
            
            # Informations du joueur
            logger.info(f"Traitement du joueur: {player.get('name')} ({player.get('id')})")
            logger.info(f"Statistiques disponibles: {len(statistics)}")
            
            # Trouver le joueur dans la base de données
            db_player = Player.query.filter_by(api_id=player.get('id')).first()
            
            if not db_player:
                # Créer le joueur s'il n'existe pas
                logger.info(f"Création du joueur: {player.get('name')}")
                
                # Extraire la date de naissance si disponible
                date_of_birth = None
                birth_data = player.get('birth', {})
                if birth_data and birth_data.get('date'):
                    try:
                        date_of_birth = datetime.strptime(birth_data.get('date'), '%Y-%m-%d')
                    except Exception as e:
                        logger.warning(f"Erreur lors de la conversion de la date: {e}")
                
                # Récupérer l'équipe depuis les statistiques
                club_id = None
                if statistics and len(statistics) > 0:
                    team_data = statistics[0].get('team', {})
                    if team_data and team_data.get('id'):
                        team_id = team_data.get('id')
                        club = Club.query.filter_by(api_id=team_id).first()
                        if club:
                            club_id = club.id
                        else:
                            # Créer le club s'il n'existe pas
                            if team_data.get('name'):
                                logger.info(f"Création du club: {team_data.get('name')}")
                                club = Club(
                                    api_id=team_id,
                                    name=team_data.get('name'),
                                    short_name=team_data.get('name')[:3].upper() if team_data.get('name') else None,
                                    crest=team_data.get('logo')
                                )
                                db.session.add(club)
                                db.session.flush()  # Obtenir l'ID sans commit
                                club_id = club.id
                
                # Créer le joueur
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
                db.session.flush()  # Pour obtenir l'ID sans commit complet
                players_count += 1
            else:
                # Mise à jour des données du joueur
                logger.info(f"Mise à jour du joueur: {player.get('name')}")
                db_player.name = player.get('name', db_player.name)
                db_player.position = player.get('position', db_player.position)
                db_player.photo_url = player.get('photo', db_player.photo_url)
                
                # Mise à jour du club si disponible
                if statistics and len(statistics) > 0:
                    team_data = statistics[0].get('team', {})
                    if team_data and team_data.get('id'):
                        team_id = team_data.get('id')
                        club = Club.query.filter_by(api_id=team_id).first()
                        if club:
                            db_player.club_id = club.id
            
            # Traiter les statistiques
            for stat in statistics:
                # Extraire les informations de la ligue et de la saison
                league = stat.get('league', {})
                season = str(league.get('season', ''))
                
                if not season:
                    logger.warning(f"Saison manquante pour les statistiques de {db_player.name}")
                    continue
                
                # Formater la saison (par exemple, "2023" devient "2023/2024")
                try:
                    season_year = int(season)
                    formatted_season = f"{season_year}/{season_year+1}"
                except:
                    formatted_season = season
                
                logger.info(f"Traitement des statistiques pour la saison {formatted_season}")
                
                # Rechercher ou créer l'enregistrement de statistiques
                db_stats = PlayerStats.query.filter_by(player_id=db_player.id, season=formatted_season).first()
                
                if not db_stats:
                    logger.info(f"Création des statistiques pour {db_player.name}, saison {formatted_season}")
                    db_stats = PlayerStats(player_id=db_player.id, season=formatted_season)
                    db.session.add(db_stats)
                else:
                    logger.info(f"Mise à jour des statistiques pour {db_player.name}, saison {formatted_season}")
                
                # Mettre à jour les statistiques
                try:
                    self._update_player_stats_from_api(db_stats, stat)
                    stats_count += 1
                except Exception as e:
                    logger.error(f"Erreur lors de la mise à jour des statistiques: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
        
        # Sauvegarder toutes les modifications
        try:
            db.session.commit()
            logger.info(f"Importation des joueurs terminée: {players_count} joueurs, {stats_count} statistiques")
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde: {str(e)}")
            db.session.rollback()
    
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
            return {
                'type': 'team_statistics',
                'status': 'success'
            }
                
        # Cas 2: Statistiques de joueurs (endpoint: players)
        try:
            from app.models.player_stats import PlayerStats
            from app.models.player import Player
            
            players_count = 0
            
            with self.app.app_context():
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
            
            return {
                'type': 'player_statistics',
                'count': players_count,
                'status': 'success'
            }
        
        except Exception as e:
            logger.error(f"Erreur lors du traitement des données de statistiques: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            db.session.rollback()
            return {
                'status': 'error',
                'error': str(e)
            }
    
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
            with self.app.app_context():
                from app.models.club import Club
                from app.models.team_stats import TeamStats
                from app import db
                from datetime import datetime
                
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
                    if isinstance(goals_for, dict):
                        if 'total' in goals_for:
                            total_for = goals_for['total']
                            if isinstance(total_for, dict) and 'total' in total_for:
                                db_stats.goals_for = total_for['total'] or 0
                            else:
                                db_stats.goals_for = total_for or 0
                        
                        # Statistiques de buts marqués par minute
                        minute_for = goals_for.get('minute', {})
                        if isinstance(minute_for, dict):
                            # Si le modèle a ces champs, mettez-les à jour
                            for time_range, data in minute_for.items():
                                if not isinstance(data, dict) or 'total' not in data:
                                    continue
                                
                                field_name = f"goals_for_{time_range.replace('-', '_')}"
                                if hasattr(db_stats, field_name):
                                    setattr(db_stats, field_name, data['total'] or 0)
                    
                    # Buts contre
                    goals_against = goals.get('against', {})
                    if isinstance(goals_against, dict):
                        if 'total' in goals_against:
                            total_against = goals_against['total']
                            if isinstance(total_against, dict) and 'total' in total_against:
                                db_stats.goals_against = total_against['total'] or 0
                            else:
                                db_stats.goals_against = total_against or 0
                        
                        # Statistiques de buts encaissés par minute
                        minute_against = goals_against.get('minute', {})
                        if isinstance(minute_against, dict):
                            # Si le modèle a ces champs, mettez-les à jour
                            for time_range, data in minute_against.items():
                                if not isinstance(data, dict) or 'total' not in data:
                                    continue
                                
                                field_name = f"goals_against_{time_range.replace('-', '_')}"
                                if hasattr(db_stats, field_name):
                                    setattr(db_stats, field_name, data['total'] or 0)
                
                # Clean sheets
                clean_sheet = team_stats.get('clean_sheet', {})
                if isinstance(clean_sheet, dict) and 'total' in clean_sheet:
                    db_stats.clean_sheets = clean_sheet['total'] or 0
                
                # Failed to score
                failed_to_score = team_stats.get('failed_to_score', {})
                if isinstance(failed_to_score, dict) and 'total' in failed_to_score and hasattr(db_stats, 'failed_to_score'):
                    db_stats.failed_to_score = failed_to_score['total'] or 0
                
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
                                
                                # Si le modèle a ces champs, mettez-les à jour
                                field_name = f"yellow_cards_{time_range.replace('-', '_')}"
                                if hasattr(db_stats, field_name):
                                    setattr(db_stats, field_name, data['total'] or 0)
                    
                    # Cartes rouges
                    red = cards.get('red', {})
                    if isinstance(red, dict):
                        for time_range, data in red.items():
                            if isinstance(data, dict) and 'total' in data and data['total'] is not None:
                                red_count += data['total']
                                
                                # Si le modèle a ces champs, mettez-les à jour
                                field_name = f"red_cards_{time_range.replace('-', '_')}"
                                if hasattr(db_stats, field_name):
                                    setattr(db_stats, field_name, data['total'] or 0)
                    
                    db_stats.yellow_cards = yellow_count
                    db_stats.red_cards = red_count
                
                # Penaltys statistics
                penalty = team_stats.get('penalty', {})
                if isinstance(penalty, dict):
                    if 'scored' in penalty and hasattr(db_stats, 'penalties_scored'):
                        db_stats.penalties_scored = penalty['scored'].get('total', 0) if isinstance(penalty['scored'], dict) else 0
                    if 'missed' in penalty and hasattr(db_stats, 'penalties_missed'):
                        db_stats.penalties_missed = penalty['missed'].get('total', 0) if isinstance(penalty['missed'], dict) else 0
                    if 'won' in penalty and hasattr(db_stats, 'penalties_won'):
                        db_stats.penalties_won = penalty['won'] or 0
                    if 'committed' in penalty and hasattr(db_stats, 'penalties_committed'):
                        db_stats.penalties_committed = penalty['committed'] or 0
                
                # Lineups (formations)
                lineups = team_stats.get('lineups', [])
                if isinstance(lineups, list) and lineups and hasattr(db_stats, 'most_used_formation'):
                    # Trouver la formation la plus utilisée
                    best_lineup = max(lineups, key=lambda x: x.get('played', 0))
                    db_stats.most_used_formation = best_lineup.get('formation')
                
                # Mise à jour timestamp
                db_stats.updated_at = datetime.utcnow()
                
                # Sauvegarder les modifications
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
            # Fonction de sécurité pour traiter les valeurs None ou vides
            def get_safe_value(data_dict, key, default=0):
                value = data_dict.get(key)
                if value is None or value == '':
                    return default
                return value
            
            # Mise à jour des statistiques de base
            games = api_stats.get('games', {})
            if isinstance(games, dict):
                db_stats.matches_played = get_safe_value(games, 'appearences') or get_safe_value(games, 'appearances')
                db_stats.minutes_played = get_safe_value(games, 'minutes')
            
            # Buts et passes décisives
            goals = api_stats.get('goals', {})
            if isinstance(goals, dict):
                db_stats.goals = get_safe_value(goals, 'total')
                db_stats.assists = get_safe_value(goals, 'assists')
            
            # Discipline
            cards = api_stats.get('cards', {})
            if isinstance(cards, dict):
                db_stats.yellow_cards = get_safe_value(cards, 'yellow')
                db_stats.red_cards = get_safe_value(cards, 'red')
            
            # Statistiques offensives
            shots = api_stats.get('shots', {})
            if isinstance(shots, dict):
                db_stats.shots = get_safe_value(shots, 'total')
                db_stats.shots_on_target = get_safe_value(shots, 'on')
            
            # Passes
            passes = api_stats.get('passes', {})
            if isinstance(passes, dict):
                db_stats.passes = get_safe_value(passes, 'total')
                db_stats.key_passes = get_safe_value(passes, 'key')
                
                # Précision des passes et passes complétées
                accuracy = passes.get('accuracy')
                if accuracy is not None:
                    try:
                        # Convertir en nombre
                        if isinstance(accuracy, str):
                            accuracy = accuracy.replace('%', '')
                        accuracy_float = float(accuracy)
                        
                        # Calculer le nombre de passes réussies
                        total_passes = get_safe_value(passes, 'total')
                        if total_passes > 0:
                            db_stats.passes_completed = int(total_passes * accuracy_float / 100)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Erreur lors de la conversion de la précision des passes: {accuracy} - {e}")
            
            # Statistiques défensives
            tackles = api_stats.get('tackles', {})
            if isinstance(tackles, dict):
                db_stats.tackles = get_safe_value(tackles, 'total')
                db_stats.tackles_won = get_safe_value(tackles, 'blocks')
                db_stats.interceptions = get_safe_value(tackles, 'interceptions')
            
            # Duels
            duels = api_stats.get('duels', {})
            if isinstance(duels, dict):
                db_stats.duels_total = get_safe_value(duels, 'total')
                db_stats.duels_won = get_safe_value(duels, 'won')
            
            # Dribbles
            dribbles = api_stats.get('dribbles', {})
            if isinstance(dribbles, dict):
                db_stats.dribbles_attempts = get_safe_value(dribbles, 'attempts')
                db_stats.dribbles_success = get_safe_value(dribbles, 'success')
                db_stats.dribbles_past = get_safe_value(dribbles, 'past')
            
            # Fautes
            fouls = api_stats.get('fouls', {})
            if isinstance(fouls, dict):
                db_stats.fouls_drawn = get_safe_value(fouls, 'drawn')
                db_stats.fouls_committed = get_safe_value(fouls, 'committed')
            
            # Pénalties
            penalty = api_stats.get('penalty', {})
            if isinstance(penalty, dict):
                db_stats.penalties_won = get_safe_value(penalty, 'won')
                db_stats.penalties_committed = get_safe_value(penalty, 'commited')
                db_stats.penalties_scored = get_safe_value(penalty, 'scored')
                db_stats.penalties_missed = get_safe_value(penalty, 'missed')
                db_stats.penalties_saved = get_safe_value(penalty, 'saved')
            
            # Note globale
            rating_value = api_stats.get('rating')
            if rating_value is not None:
                try:
                    db_stats.rating = float(rating_value)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Erreur lors de la conversion de la note: {rating_value} - {e}")
            
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
    
    def _process_match_statistics(self, fixture_id):
        """
        Traite les statistiques d'un match
        
        Args:
            fixture_id: L'ID du match
        """
        try:
            # Récupérer les statistiques du match depuis l'API
            stats_data = self.get_fixture_statistics(fixture_id)
            
            if not stats_data or 'response' not in stats_data:
                logger.error("Données de statistiques de match invalides")
                return
            
            with self.app.app_context():
                from app.models.match import Match
                from app.models.match_stats import MatchStats  # Assurez-vous que ce modèle existe
                from app.models.club import Club
                
                # Récupérer le match
                db_match = Match.query.filter_by(api_id=fixture_id).first()
                if not db_match:
                    logger.warning(f"Match avec ID API {fixture_id} non trouvé dans la base de données")
                    return
                
                # Supprimer les statistiques existantes pour ce match
                MatchStats.query.filter_by(match_id=db_match.id).delete()
                
                # Traiter les statistiques pour chaque équipe
                for team_stats in stats_data['response']:
                    team_id = team_stats.get('team', {}).get('id')
                    
                    if not team_id:
                        logger.warning("ID d'équipe manquant dans les statistiques")
                        continue
                    
                    # Trouver l'équipe dans la base de données
                    db_team = Club.query.filter_by(api_id=team_id).first()
                    
                    if not db_team:
                        logger.warning(f"Équipe avec ID API {team_id} non trouvée dans la base de données")
                        continue
                    
                    # Créer un nouvel enregistrement de statistiques
                    db_stats = MatchStats(
                        match_id=db_match.id,
                        team_id=db_team.id
                    )
                    
                    # Parcourir les statistiques
                    for stat in team_stats.get('statistics', []):
                        stat_type = stat.get('type')
                        stat_value = stat.get('value')
                        
                        # Convertir en valeur numérique si possible
                        if isinstance(stat_value, str):
                            if '%' in stat_value:
                                stat_value = stat_value.replace('%', '')
                                try:
                                    stat_value = float(stat_value)
                                except (ValueError, TypeError):
                                    pass
                            else:
                                try:
                                    stat_value = int(stat_value)
                                except (ValueError, TypeError):
                                    try:
                                        stat_value = float(stat_value)
                                    except (ValueError, TypeError):
                                        pass
                        
                        # Attribuer la statistique au bon champ
                        if stat_type == 'Shots on Goal':
                            db_stats.shots_on_goal = stat_value
                        elif stat_type == 'Shots off Goal':
                            db_stats.shots_off_goal = stat_value
                        elif stat_type == 'Total Shots':
                            db_stats.total_shots = stat_value
                        elif stat_type == 'Blocked Shots':
                            db_stats.blocked_shots = stat_value
                        elif stat_type == 'Shots insidebox':
                            db_stats.shots_insidebox = stat_value
                        elif stat_type == 'Shots outsidebox':
                            db_stats.shots_outsidebox = stat_value
                        elif stat_type == 'Fouls':
                            db_stats.fouls = stat_value
                        elif stat_type == 'Corner Kicks':
                            db_stats.corner_kicks = stat_value
                        elif stat_type == 'Offsides':
                            db_stats.offsides = stat_value
                        elif stat_type == 'Ball Possession':
                            db_stats.ball_possession = stat_value
                        elif stat_type == 'Yellow Cards':
                            db_stats.yellow_cards = stat_value
                        elif stat_type == 'Red Cards':
                            db_stats.red_cards = stat_value
                        elif stat_type == 'Goalkeeper Saves':
                            db_stats.goalkeeper_saves = stat_value
                        elif stat_type == 'Total passes':
                            db_stats.total_passes = stat_value
                        elif stat_type == 'Passes accurate':
                            db_stats.passes_accurate = stat_value
                        elif stat_type == 'Passes %':
                            db_stats.passes_percent = stat_value
                    
                    db.session.add(db_stats)
                
                # Sauvegarder les modifications
                db.session.commit()
                logger.info(f"Statistiques du match {fixture_id} mises à jour")
            
        except Exception as e:
            logger.error(f"Erreur lors du traitement des statistiques de match: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            db.session.rollback()

    def _process_injuries_data(self, data):
        """
        Traite les données des blessures et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données de blessures invalides")
            return
        
        try:
            from app.models.injury import Injury  # Assurez-vous que ce modèle existe
            from app.models.player import Player
            from app.models.match import Match
            
            injuries_added = 0
            injuries_updated = 0
            
            with self.app.app_context():
                for injury_data in data['response']:
                    if not isinstance(injury_data, dict):
                        logger.warning(f"Format de données de blessure inattendu: {type(injury_data)}")
                        continue
                    
                    player_data = injury_data.get('player', {})
                    team_data = injury_data.get('team', {})
                    fixture_data = injury_data.get('fixture', {})
                    
                    player_id = player_data.get('id')
                    if not player_id:
                        logger.warning("ID de joueur manquant dans les données de blessure")
                        continue
                    
                    # Récupérer le joueur
                    db_player = Player.query.filter_by(api_id=player_id).first()
                    if not db_player:
                        logger.warning(f"Joueur avec ID API {player_id} non trouvé dans la base de données")
                        continue
                    
                    # Récupérer le match si disponible
                    db_match = None
                    fixture_id = fixture_data.get('id')
                    if fixture_id:
                        db_match = Match.query.filter_by(api_id=fixture_id).first()
                    
                    # Rechercher si la blessure existe déjà
                    injury_type = injury_data.get('type')
                    reason = injury_data.get('reason')
                    
                    db_injury = Injury.query.filter_by(
                        player_id=db_player.id,
                        type=injury_type,
                        reason=reason
                    ).first()
                    
                    if not db_injury:
                        # Créer une nouvelle blessure
                        db_injury = Injury(
                            player_id=db_player.id,
                            match_id=db_match.id if db_match else None,
                            type=injury_type,
                            reason=reason,
                            start_date=self._parse_date(injury_data.get('start')),
                            end_date=self._parse_date(injury_data.get('end'))
                        )
                        db.session.add(db_injury)
                        injuries_added += 1
                    else:
                        # Mettre à jour la blessure existante
                        db_injury.match_id = db_match.id if db_match else db_injury.match_id
                        db_injury.start_date = self._parse_date(injury_data.get('start')) or db_injury.start_date
                        db_injury.end_date = self._parse_date(injury_data.get('end')) or db_injury.end_date
                        injuries_updated += 1
                
                db.session.commit()
            
            return {
                'added': injuries_added,
                'updated': injuries_updated,
                'total': injuries_added + injuries_updated
            }
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors du traitement des données des blessures: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'status': 'error',
                'error': str(e)
            }
        
    def _parse_date(self, date_str):
        """
        Convertit une chaîne de date en objet datetime
        
        Args:
            date_str: Chaîne de date (format YYYY-MM-DD)
            
        Returns:
            Objet datetime ou None en cas d'erreur
        """
        if not date_str:
            return None
        
        try:
            from datetime import datetime
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError) as e:
            logger.warning(f"Erreur lors de la conversion de la date: {date_str} - {e}")
            return None
    
    # Méthodes manquantes à ajouter à la fin de la classe APIFootballClient

    # Méthodes d'importation planifiée
    def schedule_leagues_import(self, params=None, execution_time=None, recurrence=None):
        """
        Planifie l'importation des ligues
        
        Args:
            params: Paramètres pour la requête API
            execution_time: Date/heure d'exécution
            recurrence: Expression cron pour les tâches récurrentes
            
        Returns:
            L'ID de la tâche planifiée
        """
        return self.schedule_task(
            task_type="import_leagues",
            endpoint="leagues",
            params=params,
            execution_time=execution_time,
            recurrence=recurrence,
            description="Importation des ligues"
        )

    def schedule_teams_import(self, params=None, execution_time=None, recurrence=None):
        """
        Planifie l'importation des équipes
        
        Args:
            params: Paramètres pour la requête API
            execution_time: Date/heure d'exécution
            recurrence: Expression cron pour les tâches récurrentes
            
        Returns:
            L'ID de la tâche planifiée
        """
        return self.schedule_task(
            task_type="import_teams",
            endpoint="teams",
            params=params,
            execution_time=execution_time,
            recurrence=recurrence,
            description="Importation des équipes"
        )

    def schedule_fixtures_import(self, params=None, execution_time=None, recurrence=None):
        """
        Planifie l'importation des matches
        
        Args:
            params: Paramètres pour la requête API
            execution_time: Date/heure d'exécution
            recurrence: Expression cron pour les tâches récurrentes
            
        Returns:
            L'ID de la tâche planifiée
        """
        return self.schedule_task(
            task_type="import_fixtures",
            endpoint="fixtures",
            params=params,
            execution_time=execution_time,
            recurrence=recurrence,
            description="Importation des matches"
        )

    def schedule_standings_import(self, params=None, execution_time=None, recurrence=None):
        """
        Planifie l'importation des classements
        
        Args:
            params: Paramètres pour la requête API
            execution_time: Date/heure d'exécution
            recurrence: Expression cron pour les tâches récurrentes
            
        Returns:
            L'ID de la tâche planifiée
        """
        return self.schedule_task(
            task_type="import_standings",
            endpoint="standings",
            params=params,
            execution_time=execution_time,
            recurrence=recurrence,
            description="Importation des classements"
        )

    def schedule_players_import(self, params=None, execution_time=None, recurrence=None):
        """
        Planifie l'importation des joueurs
        
        Args:
            params: Paramètres pour la requête API
            execution_time: Date/heure d'exécution
            recurrence: Expression cron pour les tâches récurrentes
            
        Returns:
            L'ID de la tâche planifiée
        """
        return self.schedule_task(
            task_type="import_players",
            endpoint="players",
            params=params,
            execution_time=execution_time,
            recurrence=recurrence,
            description="Importation des joueurs"
        )

    # Méthodes publiques manquantes pour accéder à l'API
    def get_standings(self, league_id, season):
        """
        Récupère les classements
        
        Args:
            league_id: ID de la ligue
            season: Saison
                
        Returns:
            Les données des classements
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        return self._make_request("standings", params)

    def get_fixture_events(self, fixture_id):
        """
        Récupère les événements d'un match
        
        Args:
            fixture_id: ID du match
                
        Returns:
            Les données des événements
        """
        params = {'fixture': fixture_id}
        
        return self._make_request("fixtures/events", params)

    def get_fixture_lineups(self, fixture_id):
        """
        Récupère les compositions d'équipe d'un match
        
        Args:
            fixture_id: ID du match
                
        Returns:
            Les données des compositions
        """
        params = {'fixture': fixture_id}
        
        return self._make_request("fixtures/lineups", params)

    def get_predictions(self, fixture_id):
        """
        Récupère les prédictions pour un match
        
        Args:
            fixture_id: ID du match
                
        Returns:
            Les données des prédictions
        """
        params = {'fixture': fixture_id}
        
        return self._make_request("predictions", params)

    def get_odds(self, fixture_id=None, league_id=None, date=None, bookmaker=None, bet=None):
        """
        Récupère les cotes
        
        Args:
            fixture_id: ID du match (optionnel)
            league_id: ID de la ligue (optionnel)
            date: Date des matches (optionnel)
            bookmaker: ID du bookmaker (optionnel)
            bet: ID du type de pari (optionnel)
                
        Returns:
            Les données des cotes
        """
        params = {}
        if fixture_id:
            params['fixture'] = fixture_id
        if league_id:
            params['league'] = league_id
        if date:
            params['date'] = date
        if bookmaker:
            params['bookmaker'] = bookmaker
        if bet:
            params['bet'] = bet
        
        return self._make_request("odds", params)

    def get_transfers(self, player_id=None, team_id=None):
        """
        Récupère les transferts
        
        Args:
            player_id: ID du joueur (optionnel)
            team_id: ID de l'équipe (optionnel)
                
        Returns:
            Les données des transferts
        """
        params = {}
        if player_id:
            params['player'] = player_id
        if team_id:
            params['team'] = team_id
        
        return self._make_request("transfers", params)

    def get_trophies(self, player_id=None, coach_id=None):
        """
        Récupère les trophées
        
        Args:
            player_id: ID du joueur (optionnel)
            coach_id: ID de l'entraîneur (optionnel)
                
        Returns:
            Les données des trophées
        """
        params = {}
        if player_id:
            params['player'] = player_id
        if coach_id:
            params['coach'] = coach_id
        
        return self._make_request("trophies", params)

    def get_injuries(self, league_id=None, team_id=None, fixture_id=None, season=None, date=None, ids=None):
        """
        Récupère les blessures
        
        Args:
            league_id: ID de la ligue (optionnel)
            team_id: ID de l'équipe (optionnel)
            fixture_id: ID du match (optionnel)
            season: Saison (optionnel)
            date: Date (optionnel, format YYYY-MM-DD)
            ids: Liste d'IDs de fixtures séparés par des tirets (optionnel)
            
        Returns:
            Les données des blessures
        """
        params = {}
        if league_id:
            params['league'] = league_id
        if team_id:
            params['team'] = team_id
        if fixture_id:
            params['fixture'] = fixture_id
        if season:
            params['season'] = season
        if date:
            params['date'] = date
        if ids:
            params['ids'] = ids
        
        return self._make_request("injuries", params)

    def get_coachs(self, team_id=None, coach_id=None):
        """
        Récupère les entraîneurs
        
        Args:
            team_id: ID de l'équipe (optionnel)
            coach_id: ID de l'entraîneur (optionnel)
                
        Returns:
            Les données des entraîneurs
        """
        params = {}
        if team_id:
            params['team'] = team_id
        if coach_id:
            params['id'] = coach_id
        
        return self._make_request("coachs", params)

    # Méthodes de traitement des données manquantes
    def _process_coachs_data(self, data):
        """
        Traite les données des entraîneurs et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données d'entraîneurs invalides")
            return
        
        try:
            from app.models.coach import Coach
            from app.models.club import Club
            from app.models.coach_career import CoachCareer
            
            coachs_added = 0
            coachs_updated = 0
            careers_added = 0
            
            with self.app.app_context():
                # Parcourir les données des entraîneurs
                for coach_data in data['response']:
                    if not isinstance(coach_data, dict):
                        logger.warning(f"Format de données d'entraîneur inattendu: {type(coach_data)}")
                        continue
                    
                    # Extraire les données de base de l'entraîneur
                    coach_id = coach_data.get('id')
                    if not coach_id:
                        logger.warning("ID de l'entraîneur manquant")
                        continue
                    
                    # Récupérer l'entraîneur existant ou en créer un nouveau
                    db_coach = Coach.query.filter_by(api_id=coach_id).first()
                    
                    # Extraire les données personnelles
                    name = coach_data.get('name')
                    first_name = coach_data.get('firstname')
                    last_name = coach_data.get('lastname')
                    
                    # Date de naissance
                    date_of_birth = None
                    birth_data = coach_data.get('birth', {})
                    if birth_data and birth_data.get('date'):
                        try:
                            date_of_birth = datetime.strptime(birth_data.get('date'), '%Y-%m-%d').date()
                        except Exception as e:
                            logger.warning(f"Erreur lors de la conversion de la date: {e}")
                    
                    # Nationalité et photo
                    nationality = coach_data.get('nationality')
                    photo = coach_data.get('photo')
                    
                    # Créer ou mettre à jour l'entraîneur
                    if not db_coach:
                        db_coach = Coach(
                            api_id=coach_id,
                            name=name,
                            first_name=first_name,
                            last_name=last_name,
                            date_of_birth=date_of_birth,
                            nationality=nationality,
                            photo_url=photo
                        )
                        db.session.add(db_coach)
                        db.session.flush()
                        coachs_added += 1
                    else:
                        db_coach.name = name if name else db_coach.name
                        db_coach.first_name = first_name if first_name else db_coach.first_name
                        db_coach.last_name = last_name if last_name else db_coach.last_name
                        db_coach.date_of_birth = date_of_birth if date_of_birth else db_coach.date_of_birth
                        db_coach.nationality = nationality if nationality else db_coach.nationality
                        db_coach.photo_url = photo if photo else db_coach.photo_url
                        coachs_updated += 1
                    
                    # Supprimer les anciennes carrières pour cet entraîneur
                    CoachCareer.query.filter_by(coach_id=db_coach.id).delete()
                    
                    # Traiter les carrières de l'entraîneur
                    career_data = coach_data.get('career', [])
                    if isinstance(career_data, list):
                        for career_entry in career_data:
                            if not isinstance(career_entry, dict):
                                continue
                            
                            # Récupérer l'équipe
                            team_data = career_entry.get('team', {})
                            if not team_data or 'id' not in team_data:
                                continue
                            
                            team = Club.query.filter_by(api_id=team_data.get('id')).first()
                            if not team and team_data.get('id'):
                                # Créer l'équipe si elle n'existe pas
                                team = Club(
                                    api_id=team_data.get('id'),
                                    name=team_data.get('name'),
                                    crest=team_data.get('logo')
                                )
                                db.session.add(team)
                                db.session.flush()
                            
                            # Extraire les dates
                            start_date = None
                            end_date = None
                            
                            if career_entry.get('start'):
                                try:
                                    start_date = datetime.strptime(career_entry.get('start'), '%Y-%m-%d')
                                except (ValueError, TypeError) as e:
                                    logger.warning(f"Erreur lors de la conversion de la date de début: {e}")
                            
                            if career_entry.get('end'):
                                try:
                                    end_date = datetime.strptime(career_entry.get('end'), '%Y-%m-%d')
                                except (ValueError, TypeError) as e:
                                    logger.warning(f"Erreur lors de la conversion de la date de fin: {e}")
                            
                            # Créer une nouvelle entrée de carrière
                            db_career = CoachCareer(
                                coach_id=db_coach.id,
                                team_id=team.id if team else None,
                                start_date=start_date,
                                end_date=end_date
                            )
                            db.session.add(db_career)
                            careers_added += 1
                
                # Sauvegarder les modifications
                db.session.commit()
                
            logger.info(f"Importation terminée: {coachs_added} entraîneurs ajoutés, {coachs_updated} mis à jour, {careers_added} carrières")
            return {
                'coachs_added': coachs_added,
                'coachs_updated': coachs_updated,
                'careers_added': careers_added,
                'total': coachs_added + coachs_updated
            }
        
        except Exception as e:
            logger.error(f"Erreur lors du traitement des données des entraîneurs: {str(e)}")
            db.session.rollback()
            import traceback
            logger.error(traceback.format_exc())

    def _process_predictions_data(self, data):
        """
        Traite les données des prédictions et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données de prédictions invalides")
            return
        
        try:
            from app.models.match import Match
            from app.models.prediction import Prediction
            
            predictions_added = 0
            predictions_updated = 0
            
            with self.app.app_context():
                # Extraire l'ID du match des paramètres
                fixture_id = None
                if data.get('parameters'):
                    fixture_id = data['parameters'].get('fixture')
                
                if not fixture_id:
                    logger.warning("ID du match manquant dans les paramètres")
                    return {'error': 'Paramètres manquants'}
                
                # Récupérer le match
                db_match = Match.query.filter_by(api_id=fixture_id).first()
                if not db_match:
                    logger.warning(f"Match avec ID API {fixture_id} non trouvé dans la base de données")
                    return {'error': 'Match non trouvé'}
                
                # Supprimer les anciennes prédictions pour ce match
                Prediction.query.filter_by(match_id=db_match.id).delete()
                
                # Parcourir les données des prédictions
                for prediction_data in data['response']:
                    if not isinstance(prediction_data, dict):
                        logger.warning(f"Format de données de prédiction inattendu: {type(prediction_data)}")
                        continue
                    
                    # Extraire les différentes sections de prédictions
                    predictions = prediction_data.get('predictions', {})
                    comparison = prediction_data.get('comparison', {})
                    teams = prediction_data.get('teams', {})
                    
                    if not isinstance(predictions, dict) or not isinstance(comparison, dict) or not isinstance(teams, dict):
                        logger.warning("Structure de données de prédiction inattendue")
                        continue
                    
                    # Extraire les prédictions
                    winner_id = None
                    winner_name = predictions.get('winner', {}).get('name')
                    winner_comment = predictions.get('winner', {}).get('comment')
                    
                    # Trouver l'ID de l'équipe gagnante prédite
                    if winner_name:
                        if teams.get('home', {}).get('name') == winner_name:
                            winner_id = db_match.home_team_id
                        elif teams.get('away', {}).get('name') == winner_name:
                            winner_id = db_match.away_team_id
                    
                    # Valeurs de prédiction
                    win_or_draw = predictions.get('win_or_draw')
                    under_over = predictions.get('under_over')
                    goals = predictions.get('goals')
                    advice = predictions.get('advice')
                    
                    # Comparaison des équipes
                    home_att = comparison.get('att', {}).get('home')
                    away_att = comparison.get('att', {}).get('away')
                    home_def = comparison.get('def', {}).get('home')
                    away_def = comparison.get('def', {}).get('away')
                    home_mid = comparison.get('mid', {}).get('home')
                    away_mid = comparison.get('mid', {}).get('away')
                    home_power = comparison.get('total', {}).get('home')
                    away_power = comparison.get('total', {}).get('away')
                    
                    # Forme des équipes
                    home_form = teams.get('home', {}).get('form')
                    away_form = teams.get('away', {}).get('form')
                    
                    # Créer une nouvelle prédiction
                    db_prediction = Prediction(
                        match_id=db_match.id,
                        winner_id=winner_id,
                        winner_comment=winner_comment,
                        win_or_draw=win_or_draw,
                        under_over=under_over,
                        goals=goals,
                        advice=advice,
                        home_att=home_att,
                        away_att=away_att,
                        home_def=home_def,
                        away_def=away_def,
                        home_mid=home_mid,
                        away_mid=away_mid,
                        home_power=home_power,
                        away_power=away_power,
                        home_form=home_form,
                        away_form=away_form
                    )
                    db.session.add(db_prediction)
                    predictions_added += 1
                
                # Sauvegarder les modifications
                db.session.commit()
                
            logger.info(f"Importation terminée: {predictions_added} prédictions ajoutées")
            return {
                'added': predictions_added,
                'updated': predictions_updated,
                'total': predictions_added + predictions_updated
            }
        
        except Exception as e:
            logger.error(f"Erreur lors du traitement des données des prédictions: {str(e)}")
            db.session.rollback()
            import traceback
            logger.error(traceback.format_exc())

    def _process_odds_data(self, data):
        """
        Traite les données des cotes et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données de cotes invalides")
            return
        
        try:
            from app.models.match import Match
            from app.models.bookmaker import Bookmaker
            from app.models.bet import Bet
            from app.models.odd import Odd
            
            odds_added = 0
            bookmakers_added = 0
            bets_added = 0
            
            with self.app.app_context():
                # Parcourir les données des cotes
                for fixture_odds in data['response']:
                    if not isinstance(fixture_odds, dict):
                        logger.warning(f"Format de données de cotes inattendu: {type(fixture_odds)}")
                        continue
                    
                    # Récupérer le match
                    fixture_id = fixture_odds.get('fixture', {}).get('id')
                    if not fixture_id:
                        logger.warning("ID du match manquant dans les cotes")
                        continue
                    
                    db_match = Match.query.filter_by(api_id=fixture_id).first()
                    if not db_match:
                        logger.warning(f"Match avec ID API {fixture_id} non trouvé dans la base de données")
                        continue
                    
                    # Supprimer les anciennes cotes pour ce match
                    Odd.query.filter_by(match_id=db_match.id).delete()
                    
                    # Parcourir les bookmakers
                    bookmakers_data = fixture_odds.get('bookmakers', [])
                    if not isinstance(bookmakers_data, list):
                        continue
                    
                    for bookmaker_data in bookmakers_data:
                        if not isinstance(bookmaker_data, dict):
                            continue
                        
                        # Récupérer ou créer le bookmaker
                        bookmaker_id = bookmaker_data.get('id')
                        bookmaker_name = bookmaker_data.get('name')
                        
                        if not bookmaker_id or not bookmaker_name:
                            continue
                        
                        db_bookmaker = Bookmaker.query.filter_by(api_id=bookmaker_id).first()
                        if not db_bookmaker:
                            db_bookmaker = Bookmaker(
                                api_id=bookmaker_id,
                                name=bookmaker_name
                            )
                            db.session.add(db_bookmaker)
                            db.session.flush()
                            bookmakers_added += 1
                        
                        # Parcourir les paris
                        bets_data = bookmaker_data.get('bets', [])
                        if not isinstance(bets_data, list):
                            continue
                        
                        for bet_data in bets_data:
                            if not isinstance(bet_data, dict):
                                continue
                            
                            # Récupérer ou créer le type de pari
                            bet_id = bet_data.get('id')
                            bet_name = bet_data.get('name')
                            
                            if not bet_id or not bet_name:
                                continue
                            
                            db_bet = Bet.query.filter_by(api_id=bet_id).first()
                            if not db_bet:
                                db_bet = Bet(
                                    api_id=bet_id,
                                    name=bet_name
                                )
                                db.session.add(db_bet)
                                db.session.flush()
                                bets_added += 1
                            
                            # Parcourir les valeurs de cotes
                            values_data = bet_data.get('values', [])
                            if not isinstance(values_data, list):
                                continue
                            
                            for value_data in values_data:
                                if not isinstance(value_data, dict):
                                    continue
                                
                                # Extraire les détails de la cote
                                value = value_data.get('value')
                                odd_value = value_data.get('odd')
                                
                                if not value or not odd_value:
                                    continue
                                
                                # Créer une nouvelle cote
                                db_odd = Odd(
                                    match_id=db_match.id,
                                    bookmaker_id=db_bookmaker.id,
                                    bet_id=db_bet.id,
                                    value=value,
                                    odd=float(odd_value)
                                )
                                db.session.add(db_odd)
                                odds_added += 1
                
                # Sauvegarder les modifications
                db.session.commit()
                
            logger.info(f"Importation terminée: {odds_added} cotes, {bookmakers_added} bookmakers, {bets_added} types de paris")
            return {
                'odds_added': odds_added,
                'bookmakers_added': bookmakers_added,
                'bets_added': bets_added,
                'total': odds_added
            }
        
        except Exception as e:
            logger.error(f"Erreur lors du traitement des données des cotes: {str(e)}")
            db.session.rollback()
            import traceback
            logger.error(traceback.format_exc())

    # Modifications à apporter à api_football_client3.py

    # 1. Ajouter les endpoints manquants pour les nouvelles fonctionnalités

    def get_injuries(self, league_id=None, team_id=None, fixture_id=None, season=None, date=None, ids=None):
        """
        Récupère les blessures
        
        Args:
            league_id: ID de la ligue (optionnel)
            team_id: ID de l'équipe (optionnel)
            fixture_id: ID du match (optionnel)
            season: Saison (optionnel)
            date: Date (optionnel, format YYYY-MM-DD)
            ids: Liste d'IDs de fixtures séparés par des tirets (optionnel)
            
        Returns:
            Les données des blessures
        """
        params = {}
        if league_id:
            params['league'] = league_id
        if team_id:
            params['team'] = team_id
        if fixture_id:
            params['fixture'] = fixture_id
        if season:
            params['season'] = season
        if date:
            params['date'] = date
        if ids:
            params['ids'] = ids
        
        return self._make_request("injuries", params)

    def get_player_squads(self, team_id=None, player_id=None):
        """
        Récupère les effectifs d'équipe ou les équipes d'un joueur
        
        Args:
            team_id: ID de l'équipe (optionnel)
            player_id: ID du joueur (optionnel)
            
        Returns:
            Les données des effectifs
        """
        params = {}
        
        if team_id:
            params['team'] = team_id
        if player_id:
            params['player'] = player_id
        
        return self._make_request("players/squads", params)

    def get_player_top_scorers(self, league_id, season):
        """
        Récupère les 20 meilleurs buteurs d'une ligue
        
        Args:
            league_id: ID de la ligue
            season: Saison
            
        Returns:
            Les données des meilleurs buteurs
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        return self._make_request("players/topscorers", params)

    def get_player_top_assists(self, league_id, season):
        """
        Récupère les 20 meilleurs passeurs d'une ligue
        
        Args:
            league_id: ID de la ligue
            season: Saison
            
        Returns:
            Les données des meilleurs passeurs
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        return self._make_request("players/topassists", params)

    def get_player_top_yellow_cards(self, league_id, season):
        """
        Récupère les 20 joueurs avec le plus de cartons jaunes d'une ligue
        
        Args:
            league_id: ID de la ligue
            season: Saison
            
        Returns:
            Les données des joueurs avec le plus de cartons jaunes
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        return self._make_request("players/topyellowcards", params)

    def get_player_top_red_cards(self, league_id, season):
        """
        Récupère les 20 joueurs avec le plus de cartons rouges d'une ligue
        
        Args:
            league_id: ID de la ligue
            season: Saison
            
        Returns:
            Les données des joueurs avec le plus de cartons rouges
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        return self._make_request("players/topredcards", params)

    def get_player_teams(self, player_id):
        """
        Récupère les équipes où un joueur a joué
        
        Args:
            player_id: ID du joueur
            
        Returns:
            Les données des équipes
        """
        params = {
            'player': player_id
        }
        
        return self._make_request("players/teams", params)

    def get_player_profiles(self, player_id=None, search=None, page=1):
        """
        Récupère les profils des joueurs
        
        Args:
            player_id: ID du joueur (optionnel)
            search: Recherche par nom (optionnel, min 3 caractères)
            page: Numéro de page pour la pagination (par défaut 1)
            
        Returns:
            Les données des profils
        """
        params = {
            'page': page
        }
        
        if player_id:
            params['player'] = player_id
        if search and len(search) >= 3:
            params['search'] = search
        
        return self._make_request("players/profiles", params)

    def get_sidelined(self, player_id=None, players=None, coach_id=None, coachs=None):
        """
        Récupère les indisponibilités des joueurs ou entraîneurs
        
        Args:
            player_id: ID du joueur (optionnel)
            players: Liste d'IDs de joueurs séparés par des tirets (optionnel)
            coach_id: ID de l'entraîneur (optionnel)
            coachs: Liste d'IDs d'entraîneurs séparés par des tirets (optionnel)
            
        Returns:
            Les données des indisponibilités
        """
        params = {}
        
        if player_id:
            params['player'] = player_id
        if players:
            params['players'] = players
        if coach_id:
            params['coach'] = coach_id
        if coachs:
            params['coachs'] = coachs
        
        return self._make_request("sidelined", params)

    def get_trophies(self, player_id=None, players=None, coach_id=None, coachs=None):
        """
        Récupère les trophées des joueurs ou entraîneurs
        
        Args:
            player_id: ID du joueur (optionnel)
            players: Liste d'IDs de joueurs séparés par des tirets (optionnel)
            coach_id: ID de l'entraîneur (optionnel)
            coachs: Liste d'IDs d'entraîneurs séparés par des tirets (optionnel)
            
        Returns:
            Les données des trophées
        """
        params = {}
        
        if player_id:
            params['player'] = player_id
        if players:
            params['players'] = players
        if coach_id:
            params['coach'] = coach_id
        if coachs:
            params['coachs'] = coachs
        
        return self._make_request("trophies", params)

    def get_odds_live(self, fixture_id=None, league_id=None, bet_id=None):
        """
        Récupère les cotes en direct
        
        Args:
            fixture_id: ID du match (optionnel)
            league_id: ID de la ligue (optionnel)
            bet_id: ID du type de pari (optionnel)
            
        Returns:
            Les données des cotes en direct
        """
        params = {}
        
        if fixture_id:
            params['fixture'] = fixture_id
        if league_id:
            params['league'] = league_id
        if bet_id:
            params['bet'] = bet_id
        
        return self._make_request("odds/live", params)

    def get_odds_live_bets(self, id=None, search=None):
        """
        Récupère les types de paris pour les cotes en direct
        
        Args:
            id: ID du type de pari (optionnel)
            search: Recherche par nom (optionnel, min 3 caractères)
            
        Returns:
            Les données des types de paris
        """
        params = {}
        
        if id:
            params['id'] = id
        if search and len(search) >= 3:
            params['search'] = search
        
        return self._make_request("odds/live/bets", params)

    # 2. Améliorer les méthodes existantes pour prendre en compte les nouveaux paramètres

    def get_fixtures(self, id=None, ids=None, live=None, date=None, league_id=None, season=None, team_id=None, 
                    last=None, next=None, from_date=None, to_date=None, round=None, status=None, venue_id=None, timezone=None):
        """
        Récupère les matches
        
        Args:
            id: ID du match (optionnel)
            ids: Plusieurs IDs de matches séparés par des tirets (optionnel, max 20)
            live: Matches en direct, 'all' ou IDs de ligues (optionnel)
            date: Date des matches (optionnel, format YYYY-MM-DD)
            league_id: ID de la ligue (optionnel)
            season: Saison (optionnel)
            team_id: ID de l'équipe (optionnel)
            last: X derniers matches (optionnel)
            next: X prochains matches (optionnel)
            from_date: Date de début (optionnel, format YYYY-MM-DD)
            to_date: Date de fin (optionnel, format YYYY-MM-DD)
            round: Tour de la compétition (optionnel)
            status: Statut du match (optionnel, ex: 'NS', 'NS-PST-FT')
            venue_id: ID du stade (optionnel)
            timezone: Fuseau horaire (optionnel)
            
        Returns:
            Les données des matches
        """
        params = {}
        
        if id:
            params['id'] = id
        if ids:
            params['ids'] = ids
        if live:
            params['live'] = live
        if date:
            params['date'] = date
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if team_id:
            params['team'] = team_id
        if last:
            params['last'] = last
        if next:
            params['next'] = next
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        if round:
            params['round'] = round
        if status:
            params['status'] = status
        if venue_id:
            params['venue'] = venue_id
        if timezone:
            params['timezone'] = timezone
        
        return self._make_request("fixtures", params)

    def get_fixture_rounds(self, league_id, season, current=None, dates=None, timezone=None):
        """
        Récupère les tours d'une compétition
        
        Args:
            league_id: ID de la ligue
            season: Saison
            current: Uniquement le tour actuel (optionnel, 'true' ou 'false')
            dates: Inclure les dates des tours (optionnel, 'true' ou 'false')
            timezone: Fuseau horaire (optionnel)
            
        Returns:
            Les données des tours
        """
        params = {
            'league': league_id,
            'season': season
        }
        
        if current:
            params['current'] = current
        if dates:
            params['dates'] = dates
        if timezone:
            params['timezone'] = timezone
        
        return self._make_request("fixtures/rounds", params)

    def get_fixture_statistics(self, fixture_id, team_id=None, type=None, half=None):
        """
        Récupère les statistiques d'un match
        
        Args:
            fixture_id: ID du match
            team_id: ID de l'équipe (optionnel)
            type: Type de statistique (optionnel)
            half: Récupérer les stats de la mi-temps (optionnel, 'true' ou 'false')
            
        Returns:
            Les données des statistiques
        """
        params = {
            'fixture': fixture_id
        }
        
        if team_id:
            params['team'] = team_id
        if type:
            params['type'] = type
        if half:
            params['half'] = half
        
        return self._make_request("fixtures/statistics", params)

    def get_teams(self, id=None, name=None, league_id=None, season=None, country=None, code=None, venue_id=None, search=None):
        """
        Récupère les équipes
        
        Args:
            id: ID de l'équipe (optionnel)
            name: Nom de l'équipe (optionnel)
            league_id: ID de la ligue (optionnel)
            season: Saison (optionnel)
            country: Pays de l'équipe (optionnel)
            code: Code de l'équipe (optionnel, 3 caractères)
            venue_id: ID du stade (optionnel)
            search: Recherche par nom ou pays (optionnel, min 3 caractères)
            
        Returns:
            Les données des équipes
        """
        params = {}
        
        if id:
            params['id'] = id
        if name:
            params['name'] = name
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if country:
            params['country'] = country
        if code:
            params['code'] = code
        if venue_id:
            params['venue'] = venue_id
        if search and len(search) >= 3:
            params['search'] = search
        
        return self._make_request("teams", params)

    def get_teams_countries(self):
        """
        Récupère la liste des pays disponibles pour les équipes
        
        Returns:
            Les données des pays
        """
        return self._make_request("teams/countries")

    def get_odds(self, fixture_id=None, league_id=None, season=None, date=None, timezone=None, page=1, 
                bookmaker_id=None, bet_id=None):
        """
        Récupère les cotes
        
        Args:
            fixture_id: ID du match (optionnel)
            league_id: ID de la ligue (optionnel)
            season: Saison (optionnel)
            date: Date (optionnel, format YYYY-MM-DD)
            timezone: Fuseau horaire (optionnel)
            page: Numéro de page pour la pagination (par défaut 1)
            bookmaker_id: ID du bookmaker (optionnel)
            bet_id: ID du type de pari (optionnel)
            
        Returns:
            Les données des cotes
        """
        params = {
            'page': page
        }
        
        if fixture_id:
            params['fixture'] = fixture_id
        if league_id:
            params['league'] = league_id
        if season:
            params['season'] = season
        if date:
            params['date'] = date
        if timezone:
            params['timezone'] = timezone
        if bookmaker_id:
            params['bookmaker'] = bookmaker_id
        if bet_id:
            params['bet'] = bet_id
        
        return self._make_request("odds", params)

    def get_odds_mapping(self, page=1):
        """
        Récupère la correspondance des IDs de matches pour les cotes
        
        Args:
            page: Numéro de page pour la pagination (par défaut 1)
            
        Returns:
            Les données de correspondance
        """
        params = {
            'page': page
        }
        
        return self._make_request("odds/mapping", params)

    def get_odds_bookmakers(self, id=None, search=None):
        """
        Récupère les bookmakers
        
        Args:
            id: ID du bookmaker (optionnel)
            search: Recherche par nom (optionnel, min 3 caractères)
            
        Returns:
            Les données des bookmakers
        """
        params = {}
        
        if id:
            params['id'] = id
        if search and len(search) >= 3:
            params['search'] = search
        
        return self._make_request("odds/bookmakers", params)

    def get_odds_bets(self, id=None, search=None):
        """
        Récupère les types de paris
        
        Args:
            id: ID du type de pari (optionnel)
            search: Recherche par nom (optionnel, min 3 caractères)
            
        Returns:
            Les données des types de paris
        """
        params = {}
        
        if id:
            params['id'] = id
        if search and len(search) >= 3:
            params['search'] = search
        
        return self._make_request("odds/bets", params)

    def get_timezone(self):
        """
        Récupère la liste des fuseaux horaires disponibles
        
        Returns:
            Les données des fuseaux horaires
        """
        return self._make_request("timezone")