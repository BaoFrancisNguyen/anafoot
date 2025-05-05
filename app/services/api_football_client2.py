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
        self.api_key = app.config.get('API_FOOTBALL_KEY')
        
        # Configurer le scheduler avec stockage dans la base de données
        jobstores = {
            'default': SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI'])
        }
        self.scheduler = BackgroundScheduler(jobstores=jobstores)
        self.scheduler.start()
        
        # Restaurer les tâches planifiées depuis la base de données
        with app.app_context():
            try:
                self._restore_scheduled_tasks()
            except Exception as e:
                logger.error(f"Erreur lors de la restauration des tâches planifiées: {str(e)}")
            
            # Démarrer le worker de traitement de la file d'attente
            self._start_queue_worker()
        
        logger.info("API Football Client initialisé avec succès")
    
    def _get_headers(self):
        """Retourne les en-têtes pour les requêtes API"""
        if not self.api_key:
            logger.error("API key manquante - Veuillez définir API_FOOTBALL_KEY dans la configuration")
            return {}
            
        # Version API-Sports
        headers = {
            'x-apisports-key': self.api_key
        }
        
        # Pour RapidAPI, utilisez plutôt :
        # headers = {
        #     'x-rapidapi-key': self.api_key,
        #     'x-rapidapi-host': self.host
        # }
        
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
            # Vérifier s'il reste des requêtes disponibles
            with self.app.app_context():
                remaining = self.get_remaining_requests()
                if remaining <= 0:
                    logger.warning("Quota d'API épuisé pour aujourd'hui")
                    return {"errors": ["Quota d'API épuisé"]}
            
            headers = self._get_headers()
            if not headers:
                return {"errors": ["Configuration API manquante"]}
                
            logger.debug(f"API Request: URL={url}, Params={params}")
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            # Enregistrer l'utilisation de l'API
            with self.app.app_context():
                self._log_api_request(endpoint, response.status_code)
            
            # Gérer les entêtes de la réponse API pour les quotas
            if 'x-ratelimit-requests-remaining' in response.headers:
                logger.info(f"Requêtes API restantes: {response.headers['x-ratelimit-requests-remaining']}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Erreur API: {response.status_code} - {response.text}")
                return {"errors": [f"Erreur API: {response.status_code}"]}
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Exception lors de l'appel à l'API: {str(e)}")
            return {"errors": [f"Erreur de connexion: {str(e)}"]}
        except json.JSONDecodeError:
            logger.error("Erreur de décodage JSON de la réponse")
            return {"errors": ["Erreur de décodage JSON"]}
        except Exception as e:
            logger.error(f"Exception inattendue: {str(e)}")
            return {"errors": [f"Erreur inattendue: {str(e)}"]}
    
    def _log_api_request(self, endpoint, status_code):
        """
        Enregistre l'utilisation de l'API dans la base de données
        
        Args:
            endpoint: L'endpoint appelé
            status_code: Code de statut HTTP de la réponse
        """
        try:
            log = APIRequestLog(
                endpoint=endpoint,
                status_code=status_code,
                timestamp=datetime.utcnow()
            )
            db.session.add(log)
            
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
            db.session.rollback()
    
    def get_remaining_requests(self):
        """
        Récupère le nombre de requêtes restantes pour la journée
        
        Returns:
            Le nombre de requêtes restantes
        """
        try:
            today = datetime.utcnow().date()
            
            # Chercher le quota du jour
            quota = APIQuota.query.filter_by(date=today).first()
            
            if quota:
                return max(0, quota.limit - quota.used)
            else:
                # Si pas de quota enregistré aujourd'hui, compter manuellement
                start_of_day = datetime.combine(today, datetime.min.time())
                end_of_day = datetime.combine(today, datetime.max.time())
                
                # Compter les requêtes d'aujourd'hui
                used_requests = APIRequestLog.query.filter(
                    APIRequestLog.timestamp >= start_of_day,
                    APIRequestLog.timestamp <= end_of_day
                ).count()
                
                return max(0, self.daily_limit - used_requests)
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
                        id=f"task_{task.id}",
                        replace_existing=True
                    )
                else:
                    # Tâche unique
                    job = self.scheduler.add_job(
                        self._execute_task,
                        'date',
                        args=[task.id],
                        run_date=execution_time,
                        id=f"task_{task.id}",
                        replace_existing=True
                    )
            else:
                # Exécution immédiate - ajouter à la file d'attente
                self.requests_queue.put(task.id)
            
            return task.id
        except Exception as e:
            logger.error(f"Erreur lors de la planification de la tâche: {str(e)}")
            db.session.rollback()
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
        # Récupérer les tâches planifiées qui ne sont pas terminées
        tasks = ScheduledTask.query.filter(
            ScheduledTask.status.in_(['PENDING', 'SCHEDULED']),
            ScheduledTask.execution_time > datetime.utcnow()
        ).all()
        
        for task in tasks:
            if task.recurrence:
                # Tâche récurrente
                try:
                    self.scheduler.add_job(
                        self._execute_task,
                        'cron',
                        args=[task.id],
                        start_date=task.execution_time,
                        **self._parse_cron_expression(task.recurrence),
                        id=f"task_{task.id}",
                        replace_existing=True
                    )
                    logger.info(f"Tâche récurrente restaurée: {task.id}")
                except Exception as e:
                    logger.error(f"Erreur lors de la restauration de la tâche récurrente {task.id}: {str(e)}")
            else:
                # Tâche unique
                try:
                    self.scheduler.add_job(
                        self._execute_task,
                        'date',
                        args=[task.id],
                        run_date=task.execution_time,
                        id=f"task_{task.id}",
                        replace_existing=True
                    )
                    logger.info(f"Tâche unique restaurée: {task.id}")
                except Exception as e:
                    logger.error(f"Erreur lors de la restauration de la tâche unique {task.id}: {str(e)}")
    
    def _start_queue_worker(self):
        """Démarre le worker de traitement de la file d'attente"""
        def worker():
            logger.info("Démarrage du worker de file d'attente")
            while True:
                try:
                    # Vérifier s'il reste des requêtes pour aujourd'hui
                    with self.app.app_context():
                        remaining = self.get_remaining_requests()
                        if remaining <= 0:
                            # Pas assez de requêtes restantes, attendre jusqu'à demain
                            now = datetime.utcnow()
                            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                            sleep_time = (tomorrow - now).total_seconds()
                            logger.info(f"Quota d'API épuisé, reprise demain. En attente pour {sleep_time} secondes.")
                            time.sleep(min(sleep_time, 3600))  # Dormir au max 1h et revérifier
                            continue
                    
                    # Récupérer une tâche de la file d'attente (avec timeout)
                    task_id = self.requests_queue.get(timeout=60)
                    
                    with self.app.app_context():
                        # Exécuter la tâche
                        self._execute_task(task_id)
                        
                        # Marquer la tâche comme terminée dans la file d'attente
                        self.requests_queue.task_done()
                    
                    # Attendre un peu entre chaque requête pour éviter de surcharger l'API
                    time.sleep(2)
                    
                except queue.Empty:
                    # Pas de tâche dans la file d'attente, attendre
                    time.sleep(5)
                except Exception as e:
                    logger.error(f"Erreur dans le worker de file d'attente: {str(e)}")
                    time.sleep(5)
        
        # Démarrer le worker dans un thread séparé
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        logger.info("Worker de file d'attente démarré")
    
    def _execute_task(self, task_id):
        """
        Exécute une tâche planifiée
        
        Args:
            task_id: L'ID de la tâche à exécuter
        """
        try:
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
        elif task_type == 'import_standings':
            return self._process_standings_data(response)
        elif task_type == 'import_leagues':
            return self._process_leagues_data(response)
        elif task_type == 'import_rounds':
            return self._process_rounds_data(response)
        elif task_type == 'import_events':
            return self._process_events_data(response)
        elif task_type == 'import_lineups':
            return self._process_lineups_data(response)
        elif task_type == 'import_injuries':
            return self._process_injuries_data(response)
        elif task_type == 'import_transfers':
            return self._process_transfers_data(response)
        elif task_type == 'import_trophies':
            return self._process_trophies_data(response)
        elif task_type == 'import_coachs':
            return self._process_coachs_data(response)
        elif task_type == 'import_predictions':
            return self._process_predictions_data(response)
        elif task_type == 'import_odds':
            return self._process_odds_data(response)
        else:
            # Pour les autres types, simplement retourner les résultats
            return {
                'count': len(response.get('response', [])),
                'status': 'success'
            }
    
    def _process_teams_data(self, data):
        """
        Traite les données d'équipes et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        from app.models.club import Club
        
        if not data or 'response' not in data:
            raise Exception("Données d'équipes invalides")
        
        teams_added = 0
        teams_updated = 0
        
        for team_data in data['response']:
            if not isinstance(team_data, dict):
                logger.warning(f"Format de données d'équipe inattendu: {type(team_data)}")
                continue
                
            team = team_data.get('team', {})
            venue = team_data.get('venue', {})
            
            if not isinstance(team, dict) or not isinstance(venue, dict):
                logger.warning(f"Structure de données inattendue: team {type(team)}, venue {type(venue)}")
                continue
            
            # Création ou mise à jour de l'équipe
            try:
                # Vérifier si l'équipe existe déjà
                db_team = Club.query.filter_by(api_id=team.get('id')).first()
                
                if not db_team:
                    # Créer une nouvelle équipe
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
                    teams_added += 1
                else:
                    # Mettre à jour l'équipe existante
                    db_team.name = team.get('name', db_team.name)
                    db_team.short_name = team.get('code') or team.get('name')[:3].upper()
                    db_team.tla = team.get('code', db_team.tla)
                    db_team.crest = team.get('logo', db_team.crest)
                    db_team.founded = team.get('founded', db_team.founded)
                    db_team.venue = venue.get('name', db_team.venue)
                    db_team.address = venue.get('address', db_team.address)
                    db_team.website = team.get('website', db_team.website)
                    teams_updated += 1
            
            except Exception as e:
                logger.error(f"Erreur lors du traitement de l'équipe {team.get('name')}: {str(e)}")
        
        # Sauvegarde des modifications
        db.session.commit()
        
        return {
            'added': teams_added,
            'updated': teams_updated,
            'total': teams_added + teams_updated
        }
    
    def _process_players_data(self, data):
        """
        Traite les données de joueurs et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        from app.models.player import Player
        from app.models.club import Club
        from app.models.player_stats import PlayerStats
        
        if not data or 'response' not in data:
            raise Exception("Données de joueurs invalides")
        
        players_added = 0
        players_updated = 0
        stats_added = 0
        stats_updated = 0
        
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
            
            try:
                # Trouver ou créer le joueur
                db_player = Player.query.filter_by(api_id=player.get('id')).first()
                
                # Extraire la date de naissance si disponible
                date_of_birth = None
                birth_data = player.get('birth', {})
                if birth_data and birth_data.get('date'):
                    try:
                        date_of_birth = datetime.strptime(birth_data.get('date'), '%Y-%m-%d').date()
                    except Exception as e:
                        logger.warning(f"Erreur lors de la conversion de la date: {e}")
                
                if not db_player:
                    # Joueur non trouvé, on le crée
                    
                    # Récupérer l'équipe depuis les statistiques
                    club_id = None
                    if statistics and statistics[0].get('team', {}).get('id'):
                        team_id = statistics[0].get('team', {}).get('id')
                        club = Club.query.filter_by(api_id=team_id).first()
                        if club:
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
                    players_added += 1
                else:
                    # Mise à jour du joueur existant
                    db_player.name = player.get('name', db_player.name)
                    db_player.first_name = player.get('firstname', db_player.first_name)
                    db_player.last_name = player.get('lastname', db_player.last_name)
                    db_player.date_of_birth = date_of_birth or db_player.date_of_birth
                    db_player.nationality = player.get('nationality', db_player.nationality)
                    db_player.position = player.get('position', db_player.position)
                    db_player.photo_url = player.get('photo', db_player.photo_url)
                    
                    # Mise à jour du club si disponible
                    if statistics and statistics[0].get('team', {}).get('id'):
                        team_id = statistics[0].get('team', {}).get('id')
                        club = Club.query.filter_by(api_id=team_id).first()
                        if club:
                            db_player.club_id = club.id
                            
                    players_updated += 1
                
                # Traiter les statistiques
                for stat in statistics:
                    # Extraire la saison et la ligue
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
                    
                    # Rechercher ou créer l'enregistrement de statistiques
                    db_stats = PlayerStats.query.filter_by(player_id=db_player.id, season=formatted_season).first()
                    
                    if not db_stats:
                        db_stats = PlayerStats(player_id=db_player.id, season=formatted_season)
                        db.session.add(db_stats)
                        stats_added += 1
                    else:
                        stats_updated += 1
                    
                    # Mettre à jour les statistiques
                    self._update_player_stats_from_api(db_stats, stat)
            
            except Exception as e:
                logger.error(f"Erreur lors du traitement du joueur: {str(e)}")
                continue
        
        # Sauvegarde des modifications
        db.session.commit()
        
        return {
            'players_added': players_added,
            'players_updated': players_updated,
            'stats_added': stats_added,
            'stats_updated': stats_updated
        }
    
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
                
                # Statistiques de duels
                duels = api_stats.get('duels', {})
                if isinstance(duels, dict):
                    db_stats.duels_total = duels.get('total', 0) or 0
                    db_stats.duels_won = duels.get('won', 0) or 0
                
                # Dribbles
                dribbles = api_stats.get('dribbles', {})
                if isinstance(dribbles, dict):
                    db_stats.dribbles_attempts = dribbles.get('attempts', 0) or 0
                    db_stats.dribbles_success = dribbles.get('success', 0) or 0
                    db_stats.dribbles_past = dribbles.get('past', 0) or 0
                
                # Fautes
                fouls = api_stats.get('fouls', {})
                if isinstance(fouls, dict):
                    db_stats.fouls_drawn = fouls.get('drawn', 0) or 0
                    db_stats.fouls_committed = fouls.get('committed', 0) or 0
                
                # Pénalties
                penalty = api_stats.get('penalty', {})
                if isinstance(penalty, dict):
                    db_stats.penalties_won = penalty.get('won', 0) or 0
                    db_stats.penalties_committed = penalty.get('commited', 0) or 0
                    db_stats.penalties_scored = penalty.get('scored', 0) or 0
                    db_stats.penalties_missed = penalty.get('missed', 0) or 0
                    db_stats.penalties_saved = penalty.get('saved', 0) or 0
                
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour des statistiques du joueur: {str(e)}")

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
    
    def _process_coachs_data(self, data):
        """
        Traite les données des entraîneurs et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        from app.models.coach import Coach
        from app.models.club import Club
        from app.models.coach_career import CoachCareer
        
        if not data or 'response' not in data:
            raise Exception("Données d'entraîneurs invalides")
        
        coachs_added = 0
        coachs_updated = 0
        careers_added = 0
        
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
            age = coach_data.get('age')
            
            # Date de naissance
            date_of_birth = None
            birth_data = coach_data.get('birth', {})
            if birth_data and birth_data.get('date'):
                try:
                    date_of_birth = datetime.strptime(birth_data.get('date'), '%Y-%m-%d').date()
                except Exception as e:
                    logger.warning(f"Erreur lors de la conversion de la date: {e}")
            
            # Nationalité
            nationality = coach_data.get('nationality')
            
            # Photo
            photo = coach_data.get('photo')
            
            # Traiter les données selon qu'il s'agit d'une création ou d'une mise à jour
            if not db_coach:
                # Créer un nouvel entraîneur
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
                db.session.flush()  # Pour obtenir l'ID sans commit complet
                coachs_added += 1
            else:
                # Mettre à jour l'entraîneur existant
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
        
        return {
            'coachs_added': coachs_added,
            'coachs_updated': coachs_updated,
            'careers_added': careers_added,
            'total': coachs_added + coachs_updated
        }
    
    def _process_predictions_data(self, data):
        """
        Traite les données des prédictions et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        from app.models.match import Match
        from app.models.prediction import Prediction
        
        if not data or 'response' not in data:
            raise Exception("Données de prédictions invalides")
        
        predictions_added = 0
        predictions_updated = 0
        
        # Extraire l'ID du match des paramètres
        fixture_id = None
        if data['parameters']:
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
        db.session.commit()
        
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
            
            # Wins, draws probabilités
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
            
            # Forme et stats des équipes
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
        
        return {
            'added': predictions_added,
            'updated': predictions_updated,
            'total': predictions_added + predictions_updated
        }
    
    def _process_odds_data(self, data):
        """
        Traite les données des cotes et les enregistre dans la base de données
        
        Args:
            data: Les données de réponse de l'API
        """
        from app.models.match import Match
        from app.models.bookmaker import Bookmaker
        from app.models.bet import Bet
        from app.models.odd import Odd
        
        if not data or 'response' not in data:
            raise Exception("Données de cotes invalides")
        
        odds_added = 0
        bookmakers_added = 0
        bets_added = 0
        
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
            db.session.commit()
            
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
        
        return {
            'odds_added': odds_added,
            'bookmakers_added': bookmakers_added,
            'bets_added': bets_added,
            'total': odds_added
        }
    
    # Méthodes publiques pour les différentes API endpoints
    
    def get_leagues(self, **params):
        """
        Récupère les ligues disponibles
        
        Args:
            **params: Paramètres pour la requête API
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("leagues", params)
    
    def get_teams(self, **params):
        """
        Récupère les équipes
        
        Args:
            **params: Paramètres pour la requête API
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("teams", params)
    
    def get_team_statistics(self, **params):
        """
        Récupère les statistiques d'une équipe
        
        Args:
            **params: Paramètres pour la requête API (league, team, season requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("teams/statistics", params)
    
    def get_standings(self, **params):
        """
        Récupère les classements
        
        Args:
            **params: Paramètres pour la requête API (league, season requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("standings", params)
    
    def get_fixtures(self, **params):
        """
        Récupère les matches
        
        Args:
            **params: Paramètres pour la requête API
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("fixtures", params)
    
    def get_fixture_statistics(self, **params):
        """
        Récupère les statistiques d'un match
        
        Args:
            **params: Paramètres pour la requête API (fixture requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("fixtures/statistics", params)
    
    def get_fixture_events(self, **params):
        """
        Récupère les événements d'un match
        
        Args:
            **params: Paramètres pour la requête API (fixture requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("fixtures/events", params)
    
    def get_fixture_lineups(self, **params):
        """
        Récupère les formations d'un match
        
        Args:
            **params: Paramètres pour la requête API (fixture requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("fixtures/lineups", params)
    
    def get_players(self, **params):
        """
        Récupère les joueurs
        
        Args:
            **params: Paramètres pour la requête API
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("players", params)
    
    def get_predictions(self, **params):
        """
        Récupère les prédictions pour un match
        
        Args:
            **params: Paramètres pour la requête API (fixture requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("predictions", params)
    
    def get_odds(self, **params):
        """
        Récupère les cotes
        
        Args:
            **params: Paramètres pour la requête API
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("odds", params)
    
    def get_transfers(self, **params):
        """
        Récupère les transferts
        
        Args:
            **params: Paramètres pour la requête API (player ou team requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("transfers", params)
    
    def get_trophies(self, **params):
        """
        Récupère les trophées
        
        Args:
            **params: Paramètres pour la requête API (player ou coach requis)
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("trophies", params)
    
    def get_injuries(self, **params):
        """
        Récupère les blessures
        
        Args:
            **params: Paramètres pour la requête API
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("injuries", params)
    
    def get_coachs(self, **params):
        """
        Récupère les entraîneurs
        
        Args:
            **params: Paramètres pour la requête API
            
        Returns:
            Les données de réponse de l'API
        """
        return self._make_request("coachs", params)
    
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