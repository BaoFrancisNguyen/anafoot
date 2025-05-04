# app/services/api_football_client.py
import requests
import json
import logging
from datetime import datetime, timedelta
import time
from flask import current_app
import schedule
import threading
import queue
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from app import db
from app.models.scheduled_task import ScheduledTask
from app.models.api_request_log import APIRequestLog

logger = logging.getLogger(__name__)

# app/services/api_football_client.py (partie importante)

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
    
    def _get_headers(self):
        """Retourne les en-têtes pour les requêtes API"""
        headers = {
            'X-RapidAPI-Key': self.api_key,
            'X-RapidAPI-Host': self.host
        }
        # Afficher les en-têtes pour le débogage
        print(f"DEBUG - Headers: {headers}")
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
            print(f"DEBUG - API Request: URL={url}, Headers={headers}, Params={params}")
            
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
                    elif task.task_type == 'import_matches':
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
            team = team_data['team']
            venue = team_data.get('venue', {})
            
            # Créer ou mettre à jour l'équipe dans la base de données
            db_team = Club.query.filter_by(api_id=team['id']).first()
            
            if not db_team:
                db_team = Club(
                    api_id=team['id'],
                    name=team['name'],
                    short_name=team.get('code') or team['name'][:3].upper(),
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
                db_team.name = team['name']
                db_team.short_name = team.get('code') or team['name'][:3].upper()
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
        
        for player_data in data['response']:
            player = player_data['player']
            team_data = player_data.get('statistics', [{}])[0].get('team', {})
            
            # Trouver le club associé
            if team_data and 'id' in team_data:
                club = Club.query.filter_by(api_id=team_data['id']).first()
                club_id = club.id if club else None
            else:
                club_id = None
            
            # Créer ou mettre à jour le joueur dans la base de données
            db_player = Player.query.filter_by(api_id=player['id']).first()
            
            if not db_player:
                db_player = Player(
                    api_id=player['id'],
                    name=player['name'],
                    first_name=player.get('firstname'),
                    last_name=player.get('lastname'),
                    date_of_birth=datetime.strptime(player['birth']['date'], '%Y-%m-%d') if player.get('birth', {}).get('date') else None,
                    nationality=player.get('nationality'),
                    position=player.get('position'),
                    photo_url=player.get('photo'),
                    club_id=club_id
                )
                db.session.add(db_player)
            else:
                # Mettre à jour les informations existantes
                db_player.name = player['name']
                db_player.first_name = player.get('firstname')
                db_player.last_name = player.get('lastname')
                db_player.date_of_birth = datetime.strptime(player['birth']['date'], '%Y-%m-%d') if player.get('birth', {}).get('date') else None
                db_player.nationality = player.get('nationality')
                db_player.position = player.get('position')
                db_player.photo_url = player.get('photo')
                if club_id:
                    db_player.club_id = club_id
        
        db.session.commit()
        logger.info(f"Importation de {len(data['response'])} joueurs terminée")
    
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
        
        for match_data in data['response']:
            fixture = match_data['fixture']
            league = match_data['league']
            teams = match_data['teams']
            goals = match_data['goals']
            score = match_data['score']
            
            # Trouver les équipes associées
            home_team = Club.query.filter_by(api_id=teams['home']['id']).first()
            away_team = Club.query.filter_by(api_id=teams['away']['id']).first()
            
            if not home_team or not away_team:
                logger.warning(f"Équipe(s) non trouvée(s) pour le match {fixture['id']}")
                continue
            
            # Convertir la date du match
            try:
                match_date = datetime.strptime(fixture['date'], '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
            except:
                match_date = datetime.utcnow()
            
            # Créer ou mettre à jour le match dans la base de données
            db_match = Match.query.filter_by(api_id=fixture['id']).first()
            
            if not db_match:
                db_match = Match(
                    api_id=fixture['id'],
                    competition=league['name'],
                    season=f"{league['season']}/{league['season']+1}",
                    matchday=fixture.get('matchday'),
                    date=match_date,
                    status=fixture['status']['short'],
                    home_team_id=home_team.id,
                    away_team_id=away_team.id,
                    home_team_score=goals['home'],
                    away_team_score=goals['away'],
                    half_time_home=score.get('halftime', {}).get('home'),
                    half_time_away=score.get('halftime', {}).get('away'),
                    extra_time_home=score.get('extratime', {}).get('home'),
                    extra_time_away=score.get('extratime', {}).get('away'),
                    penalties_home=score.get('penalty', {}).get('home'),
                    penalties_away=score.get('penalty', {}).get('away')
                )
                db.session.add(db_match)
            else:
                # Mettre à jour les informations existantes
                db_match.competition = league['name']
                db_match.season = f"{league['season']}/{league['season']+1}"
                db_match.matchday = fixture.get('matchday')
                db_match.date = match_date
                db_match.status = fixture['status']['short']
                db_match.home_team_score = goals['home']
                db_match.away_team_score = goals['away']
                db_match.half_time_home = score.get('halftime', {}).get('home')
                db_match.half_time_away = score.get('halftime', {}).get('away')
                db_match.extra_time_home = score.get('extratime', {}).get('home')
                db_match.extra_time_away = score.get('extratime', {}).get('away')
                db_match.penalties_home = score.get('penalty', {}).get('home')
                db_match.penalties_away = score.get('penalty', {}).get('away')
        
        db.session.commit()
        logger.info(f"Importation de {len(data['response'])} matchs terminée")
    
    def _process_statistics_data(self, data):
        """
        Traite les données de statistiques et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        if not data or 'response' not in data:
            logger.error("Données de statistiques invalides")
            return
        
        from app.models.player_stats import PlayerStats
        from app.models.player import Player
        
        for player_data in data['response']:
            player = player_data['player']
            statistics = player_data.get('statistics', [])
            
            # Trouver le joueur associé
            db_player = Player.query.filter_by(api_id=player['id']).first()
            
            if not db_player:
                logger.warning(f"Joueur {player['id']} non trouvé")
                continue
            
            for stat in statistics:
                league = stat.get('league', {})
                team = stat.get('team', {})
                season = f"{league.get('season')}/{league.get('season')+1}" if league.get('season') else None
                
                if not season:
                    continue
                
                # Créer ou mettre à jour les statistiques dans la base de données
                db_stats = PlayerStats.query.filter_by(player_id=db_player.id, season=season).first()
                
                if not db_stats:
                    db_stats = PlayerStats(
                        player_id=db_player.id,
                        season=season
                    )
                    db.session.add(db_stats)
                
                # Mettre à jour les statistiques
                games = stat.get('games', {})
                db_stats.matches_played = games.get('appearences', 0)
                db_stats.minutes_played = games.get('minutes', 0)
                
                goals = stat.get('goals', {})
                db_stats.goals = goals.get('total', 0)
                db_stats.assists = stat.get('goals', {}).get('assists', 0)
                
                cards = stat.get('cards', {})
                db_stats.yellow_cards = cards.get('yellow', 0)
                db_stats.red_cards = cards.get('red', 0)
                
                shots = stat.get('shots', {})
                db_stats.shots = shots.get('total', 0)
                db_stats.shots_on_target = shots.get('on', 0)
                
                passes = stat.get('passes', {})
                db_stats.passes = passes.get('total', 0)
                db_stats.key_passes = passes.get('key', 0)
                db_stats.passes_completed = passes.get('accuracy') * passes.get('total') / 100 if passes.get('accuracy') and passes.get('total') else 0
                
                tackles = stat.get('tackles', {})
                db_stats.tackles = tackles.get('total', 0)
                db_stats.interceptions = tackles.get('interceptions', 0)
                
                duels = stat.get('duels', {})
                db_stats.duels = duels.get('total', 0)
                db_stats.duels_won = duels.get('won', 0)
                
                dribbles = stat.get('dribbles', {})
                
                # Statistiques spécifiques aux gardiens
                if db_player.position == 'Goalkeeper':
                    goalkeeping = stat.get('goalkeeper', {})
                    db_stats.saves = goalkeeping.get('saves', 0)
                    db_stats.goals_conceded = goalkeeping.get('goals_conceded', 0)
                    db_stats.clean_sheets = goalkeeping.get('cleansheets', 0)
                    db_stats.penalties_saved = goalkeeping.get('penalty_saved', 0)
        
        db.session.commit()
        logger.info(f"Importation des statistiques terminée")
    
    # Méthodes d'accès à l'API
    
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
    
    def get_players(self, team_id, season=None):
        """
        Récupère les joueurs d'une équipe
        
        Args:
            team_id: ID de l'équipe
            season: Saison (optionnel)
            
        Returns:
            Les données des joueurs
        """
        params = {'team': team_id}
        if season:
            params['season'] = season
        
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
    
    def get_players_statistics(self, league_id, season):
        """
        Récupère les statistiques des joueurs d'une ligue
        
        Args:
            league_id: ID de la ligue
            season: Saison
            
        Returns:
            Les données des statistiques
        """