# app/routes/api_football_routes.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from app.models.scheduled_task import ScheduledTask
from app.models.api_request_log import APIRequestLog
from app.models.api_quota import APIQuota
from app import db
from datetime import datetime, date, timedelta
import json
import logging

logger = logging.getLogger(__name__)

# Création du Blueprint
api_football_bp = Blueprint('api_football', __name__)

@api_football_bp.route('/')
def index():
    """Page d'accueil de la gestion API-Football"""
    # Calculer le quota d'API restant
    api_client = current_app.extensions['api_football']
    remaining = api_client.get_remaining_requests()
    
    # Récupérer les 10 dernières tâches planifiées
    tasks = ScheduledTask.query.order_by(ScheduledTask.id.desc()).limit(10).all()
    
    # Récupérer l'historique d'utilisation sur les 7 derniers jours
    today = date.today()
    last_week = today - timedelta(days=7)
    
    usage_history = []
    for i in range(7):
        day = last_week + timedelta(days=i+1)
        quota = APIQuota.query.filter_by(date=day).first()
        
        if not quota:
            # Compter manuellement les requêtes pour ce jour
            start_datetime = datetime.combine(day, datetime.min.time())
            end_datetime = datetime.combine(day, datetime.max.time())
            count = APIRequestLog.query.filter(
                APIRequestLog.timestamp >= start_datetime,
                APIRequestLog.timestamp <= end_datetime
            ).count()
            
            usage_history.append({
                'date': day.strftime('%d/%m'),
                'used': count,
                'limit': 100
            })
        else:
            usage_history.append({
                'date': day.strftime('%d/%m'),
                'used': quota.used,
                'limit': quota.limit
            })
    
    return render_template('api_football/index.html', 
                           remaining=remaining, 
                           tasks=tasks, 
                           usage_history=usage_history)

@api_football_bp.route('/dashboard')
def dashboard():
    """Tableau de bord des données API-Football"""
    # Calculer le quota d'API restant
    api_client = current_app.extensions['api_football']
    remaining = api_client.get_remaining_requests()
    
    # Récupérer l'historique des requêtes
    recent_requests = APIRequestLog.query.order_by(APIRequestLog.id.desc()).limit(20).all()
    
    # Récupérer les tâches planifiées
    pending_tasks = ScheduledTask.query.filter(ScheduledTask.status.in_(['PENDING', 'SCHEDULED'])).order_by(ScheduledTask.execution_time).all()
    completed_tasks = ScheduledTask.query.filter(ScheduledTask.status.in_(['COMPLETED', 'ERROR'])).order_by(ScheduledTask.last_run.desc()).limit(10).all()
    
    return render_template('api_football/dashboard.html', 
                           remaining=remaining, 
                           recent_requests=recent_requests, 
                           pending_tasks=pending_tasks, 
                           completed_tasks=completed_tasks)

@api_football_bp.route('/tasks')
def tasks():
    """Liste des tâches planifiées"""
    status_filter = request.args.get('status')
    
    # Construire la requête de base
    query = ScheduledTask.query
    
    # Appliquer le filtre de statut s'il est spécifié
    if status_filter:
        query = query.filter(ScheduledTask.status == status_filter.upper())
    
    # Trier et paginer les résultats
    tasks = query.order_by(ScheduledTask.id.desc()).all()
    
    return render_template('api_football/tasks.html', tasks=tasks, status_filter=status_filter)

@api_football_bp.route('/tasks/<int:task_id>')
def task_detail(task_id):
    """Détails d'une tâche planifiée"""
    task = ScheduledTask.query.get_or_404(task_id)
    
    # Convertir les données JSON pour l'affichage
    parameters = task.get_parameters()
    result = task.get_result()
    
    return render_template('api_football/task_detail.html', 
                           task=task, 
                           parameters=parameters, 
                           result=result)

@api_football_bp.route('/tasks/create', methods=['GET', 'POST'])
def create_task():
    """Formulaire de création de tâche planifiée"""
    if request.method == 'POST':
        task_type = request.form.get('task_type')
        endpoint = request.form.get('endpoint')
        parameters = request.form.get('parameters')
        description = request.form.get('description')
        
        # Options de planification
        schedule_type = request.form.get('schedule_type', 'now')
        
        execution_time = None
        recurrence = None
        
        if schedule_type == 'once':
            # Format: YYYY-MM-DDThh:mm
            execution_date = request.form.get('execution_date')
            execution_time = datetime.strptime(execution_date, '%Y-%m-%dT%H:%M')
        elif schedule_type == 'recurring':
            recurrence_pattern = request.form.get('recurrence_pattern')
            
            # Convertir le motif de récurrence au format cron
            recurrence = None
            if recurrence_pattern == 'daily':
                recurrence = '0 0 * * *'  # Tous les jours à minuit
            elif recurrence_pattern == 'weekly':
                day_of_week = request.form.get('day_of_week', '0')
                recurrence = f'0 0 * * {day_of_week}'  # Une fois par semaine à minuit
            elif recurrence_pattern == 'monthly':
                day_of_month = request.form.get('day_of_month', '1')
                recurrence = f'0 0 {day_of_month} * *'  # Une fois par mois à minuit
            
            # Date de début
            start_date = request.form.get('start_date')
            if start_date:
                execution_time = datetime.strptime(f"{start_date}T00:00", '%Y-%m-%dT%H:%M')
            else:
                execution_time = datetime.now()
        
        try:
            # Valider les paramètres JSON
            params_dict = {}
            if parameters:
                params_dict = json.loads(parameters)
            
            # Créer la tâche
            task = ScheduledTask(
                task_type=task_type,
                endpoint=endpoint,
                parameters=json.dumps(params_dict),
                execution_time=execution_time,
                recurrence=recurrence,
                description=description,
                status='PENDING'
            )
            db.session.add(task)
            db.session.commit()
            
            # Planifier la tâche
            api_client = current_app.extensions['api_football']
            api_client.schedule_task(
                task_type=task_type,
                endpoint=endpoint,
                params=params_dict,
                execution_time=execution_time,
                recurrence=recurrence,
                description=description
            )
            
            flash('Tâche planifiée avec succès', 'success')
            return redirect(url_for('api_football.tasks'))
        except json.JSONDecodeError:
            flash('Format JSON de paramètres invalide', 'danger')
        except Exception as e:
            flash(f'Erreur lors de la création de la tâche: {str(e)}', 'danger')
            db.session.rollback()
    
    return render_template('api_football/create_task.html')

@api_football_bp.route('/tasks/<int:task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    """Annuler une tâche planifiée"""
    task = ScheduledTask.query.get_or_404(task_id)
    
    # Vérifier si la tâche peut être annulée
    if task.status not in ['PENDING', 'SCHEDULED']:
        flash('Impossible d\'annuler une tâche déjà exécutée', 'danger')
        return redirect(url_for('api_football.task_detail', task_id=task_id))
    
    try:
        # Mettre à jour le statut
        task.status = 'CANCELLED'
        db.session.commit()
        
        # Annuler la tâche dans le scheduler
        scheduler = current_app.extensions['api_football'].scheduler
        scheduler.remove_job(f"task_{task_id}")
        
        flash('Tâche annulée avec succès', 'success')
    except Exception as e:
        flash(f'Erreur lors de l\'annulation de la tâche: {str(e)}', 'danger')
        db.session.rollback()
    
    return redirect(url_for('api_football.tasks'))

@api_football_bp.route('/tasks/<int:task_id>/execute', methods=['POST'])
def execute_task(task_id):
    """Exécuter immédiatement une tâche planifiée"""
    task = ScheduledTask.query.get_or_404(task_id)
    
    # Vérifier si la tâche peut être exécutée
    if task.status not in ['PENDING', 'SCHEDULED']:
        flash('Impossible d\'exécuter une tâche déjà terminée', 'danger')
        return redirect(url_for('api_football.task_detail', task_id=task_id))
    
    try:
        # Ajouter la tâche à la file d'attente pour exécution immédiate
        api_client = current_app.extensions['api_football']
        api_client.requests_queue.put(task.id)
        
        # Mettre à jour le statut
        task.status = 'RUNNING'
        db.session.commit()
        
        flash('Tâche mise en file d\'attente pour exécution immédiate', 'success')
    except Exception as e:
        flash(f'Erreur lors de l\'exécution de la tâche: {str(e)}', 'danger')
        db.session.rollback()
    
    return redirect(url_for('api_football.task_detail', task_id=task_id))

@api_football_bp.route('/data/import', methods=['GET', 'POST'])
def data_import():
    """Interface d'importation de données"""
    if request.method == 'POST':
        import_type = request.form.get('import_type')
        league_id = request.form.get('league_id')
        season = request.form.get('season')
        team_id = request.form.get('team_id')
        schedule_type = request.form.get('schedule_type', 'now')
        
        # Déterminer l'endpoint et les paramètres
        endpoint = None
        params = {}
        
        # DÉBUT DES MODIFICATIONS - Règles pour chaque type d'importation
        if import_type == 'teams':
            endpoint = 'teams'
            # Pour les équipes, une ligue est nécessaire
            if not league_id:
                flash('Pour importer des équipes, veuillez sélectionner une ligue', 'danger')
                return redirect(url_for('api_football.data_import'))
            
            params['league'] = league_id
            if season:
                params['season'] = season
                
        elif import_type == 'players':
            endpoint = 'players'
            
            # CORRECTION : L'API exige un ID d'équipe ou de ligue avec le paramètre season
            if not team_id and not league_id:
                flash('Pour importer des joueurs, l\'ID de l\'équipe ou de la ligue est obligatoire', 'danger')
                return redirect(url_for('api_football.data_import'))
            
            # Ajouter les paramètres
            if team_id:
                params['team'] = team_id
            elif league_id:
                params['league'] = league_id
                
            if season:
                params['season'] = season
                
        elif import_type == 'fixtures':
            endpoint = 'fixtures'
            
            # Pour les matchs, au moins un paramètre est nécessaire
            if not league_id and not team_id:
                flash('Pour importer des matchs, veuillez spécifier une ligue ou une équipe', 'danger')
                return redirect(url_for('api_football.data_import'))
                
            if league_id:
                params['league'] = league_id
            if team_id:
                params['team'] = team_id
            if season:
                params['season'] = season
                
        elif import_type == 'statistics':
            # Pour les statistiques, choisir le bon endpoint
            if team_id:
                endpoint = 'teams/statistics'
                params['team'] = team_id
                if league_id:
                    params['league'] = league_id
                else:
                    flash('Pour les statistiques d\'équipe, veuillez spécifier une ligue', 'danger')
                    return redirect(url_for('api_football.data_import'))
            else:
                endpoint = 'players'
                if not league_id:
                    flash('Pour les statistiques de joueurs, veuillez spécifier une ligue', 'danger')
                    return redirect(url_for('api_football.data_import'))
                params['league'] = league_id
            
            # La saison est obligatoire pour les statistiques
            if not season:
                flash('La saison est obligatoire pour les statistiques', 'danger')
                return redirect(url_for('api_football.data_import'))
            
            params['season'] = season
        else:
            flash('Type d\'importation non valide', 'danger')
            return redirect(url_for('api_football.data_import'))
        # FIN DES MODIFICATIONS
        
        # Options de planification
        execution_time = None
        recurrence = None
        
        if schedule_type == 'once':
            # Format: YYYY-MM-DDThh:mm
            execution_date = request.form.get('execution_date')
            execution_time = datetime.strptime(execution_date, '%Y-%m-%dT%H:%M')
        elif schedule_type == 'recurring':
            recurrence_pattern = request.form.get('recurrence_pattern')
            
            # Convertir le motif de récurrence au format cron
            if recurrence_pattern == 'daily':
                recurrence = '0 0 * * *'  # Tous les jours à minuit
            elif recurrence_pattern == 'weekly':
                day_of_week = request.form.get('day_of_week', '0')
                recurrence = f'0 0 * * {day_of_week}'  # Une fois par semaine à minuit
            elif recurrence_pattern == 'monthly':
                day_of_month = request.form.get('day_of_month', '1')
                recurrence = f'0 0 {day_of_month} * *'  # Une fois par mois à minuit
            
            # Date de début
            start_date = request.form.get('start_date')
            if start_date:
                execution_time = datetime.strptime(f"{start_date}T00:00", '%Y-%m-%dT%H:%M')
            else:
                execution_time = datetime.now()
        
        # Vérifier si les paramètres nécessaires sont présents
        if not endpoint:
            flash('Type d\'importation non valide', 'danger')
        else:
            try:
                # Description de la tâche
                description = f"Importation {import_type}"
                if league_id:
                    description += f" - Ligue {league_id}"
                if season:
                    description += f" - Saison {season}"
                if team_id:
                    description += f" - Équipe {team_id}"
                
                # Planifier la tâche
                api_client = current_app.extensions['api_football']
                task_id = api_client.schedule_task(
                    task_type=f"import_{import_type}",
                    endpoint=endpoint,
                    params=params,
                    execution_time=execution_time,
                    recurrence=recurrence,
                    description=description
                )
                
                if task_id:
                    flash('Importation planifiée avec succès', 'success')
                    return redirect(url_for('api_football.task_detail', task_id=task_id))
                else:
                    flash('Erreur lors de la planification de l\'importation', 'danger')
            except Exception as e:
                flash(f'Erreur: {str(e)}', 'danger')
    
    # Récupérer la liste des ligues disponibles
    api_client = current_app.extensions['api_football']
    leagues_data = None
    
    try:
        # Vérifier s'il reste suffisamment de requêtes API
        if api_client.get_remaining_requests() > 5:  # Garder une marge
            leagues_data = api_client.get_leagues(current=True)
    except:
        pass
    
    leagues = []
    if leagues_data and 'response' in leagues_data:
        for league_data in leagues_data['response']:
            league = league_data.get('league', {})
            country = league_data.get('country', {})
            
            leagues.append({
                'id': league.get('id'),
                'name': league.get('name'),
                'country': country.get('name'),
                'logo': league.get('logo')
            })
    
    # Si aucune ligue n'est disponible, utiliser une liste prédéfinie
    if not leagues:
        leagues = [
            {'id': 39, 'name': 'Premier League', 'country': 'Angleterre'},
            {'id': 140, 'name': 'La Liga', 'country': 'Espagne'},
            {'id': 135, 'name': 'Serie A', 'country': 'Italie'},
            {'id': 78, 'name': 'Bundesliga', 'country': 'Allemagne'},
            {'id': 61, 'name': 'Ligue 1', 'country': 'France'}
        ]
    
    return render_template('api_football/data_import.html', leagues=leagues)

@api_football_bp.route('/usage')
def usage():
    """Historique d'utilisation de l'API"""
    # Récupérer l'historique sur les 30 derniers jours
    today = date.today()
    last_month = today - timedelta(days=30)
    
    daily_usage = []
    for i in range(31):
        day = last_month + timedelta(days=i)
        quota = APIQuota.query.filter_by(date=day).first()
        
        if not quota:
            # Compter manuellement les requêtes pour ce jour
            start_datetime = datetime.combine(day, datetime.min.time())
            end_datetime = datetime.combine(day, datetime.max.time())
            count = APIRequestLog.query.filter(
                APIRequestLog.timestamp >= start_datetime,
                APIRequestLog.timestamp <= end_datetime
            ).count()
            
            daily_usage.append({
                'date': day,
                'used': count,
                'limit': 100
            })
        else:
            daily_usage.append({
                'date': day,
                'used': quota.used,
                'limit': quota.limit
            })
    
    # Récupérer l'utilisation par endpoint
    endpoint_usage = db.session.query(
        APIRequestLog.endpoint,
        db.func.count(APIRequestLog.id).label('count')
    ).group_by(APIRequestLog.endpoint).all()
    
    return render_template('api_football/usage.html', 
                           daily_usage=daily_usage, 
                           endpoint_usage=endpoint_usage)

@api_football_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    """Paramètres de l'API"""
    if request.method == 'POST':
        api_key = request.form.get('api_key')
        daily_limit = request.form.get('daily_limit', type=int)
        
        if api_key:
            current_app.config['API_FOOTBALL_KEY'] = api_key
            
            # Mise à jour du client API
            api_client = current_app.extensions['api_football']
            api_client.api_key = api_key
            
            flash('Clé API mise à jour avec succès', 'success')
        
        if daily_limit and daily_limit > 0:
            # Mettre à jour la limite quotidienne
            api_client = current_app.extensions['api_football']
            api_client.daily_limit = daily_limit
            
            # Mettre à jour la limite pour aujourd'hui
            today = date.today()
            quota = APIQuota.query.filter_by(date=today).first()
            
            if quota:
                quota.limit = daily_limit
            else:
                quota = APIQuota(date=today, limit=daily_limit)
                db.session.add(quota)
            
            db.session.commit()
            
            flash('Limite quotidienne mise à jour avec succès', 'success')
        
        return redirect(url_for('api_football.settings'))
    
    # Récupérer les paramètres actuels
    api_key = current_app.config.get('API_FOOTBALL_KEY', '')
    api_client = current_app.extensions['api_football']
    daily_limit = api_client.daily_limit
    
    return render_template('api_football/settings.html',
                           api_key=api_key,
                           daily_limit=daily_limit)

@api_football_bp.route('/test-api')
def test_api():
    """Test de l'API-Football"""
    endpoint = request.args.get('endpoint', 'status')
    
    try:
        # Récupérer le client API
        api_client = current_app.extensions['api_football']
        
        # Afficher les paramètres du client
        print(f"DEBUG - Testing API with key: {api_client.api_key[:5]}...{api_client.api_key[-5:]}")
        
        # Effectuer une requête test
        if endpoint == 'status':
            response = api_client._make_request('status')
        elif endpoint == 'leagues':
            response = api_client._make_request('leagues', {'current': 'true'})
        elif endpoint == 'teams':
            response = api_client._make_request('teams', {'league': 39, 'season': 2023})
        elif endpoint == 'players':
            response = api_client._make_request('players', {'team': 33, 'season': 2023})
        
        # Vérifier la réponse
        if response:
            return jsonify({
                'success': True,
                'message': 'Test de l\'API réussi !',
                'response': response
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Échec du test. Vérifiez les logs pour plus de détails.'
            })
    except Exception as e:
        print(f"DEBUG - API Test Error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Erreur lors du test de l\'API: {str(e)}'
        })
    
# Nouvelle route pour récupérer et afficher les classements des ligues
@api_football_bp.route('/standings/<int:league_id>/<int:season>')
def view_standings(league_id, season):
    """Affiche les classements d'une ligue pour une saison donnée"""
    try:
        # Récupérer le client API
        api_client = current_app.extensions['api_football']
        
        # Récupérer les données du classement
        response = api_client._make_request('standings', {
            'league': league_id,
            'season': season
        })
        
        if not response or 'response' not in response or not response['response']:
            flash('Aucun classement disponible pour cette ligue et cette saison', 'warning')
            return redirect(url_for('api_football.index'))
        
        standings_data = response['response'][0]['league']
        
        # Récupérer les informations sur la ligue
        league_info = None
        for code, league in LEAGUE_MAPPING.items():
            if int(league['id'].split('/')[0]) == league_id:
                league_info = league
                break
        
        # Formater les données pour le modèle
        formatted_season = f"{season}/{season+1}"
        
        return render_template('api_football/standings.html',
                              standings=standings_data,
                              season=formatted_season,
                              league_info=league_info)
                              
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des classements: {str(e)}")
        flash(f"Une erreur s'est produite: {str(e)}", 'danger')
        return redirect(url_for('api_football.index'))

# Nouvelle route pour récupérer et afficher les statistiques d'une équipe
@api_football_bp.route('/team-stats/<int:team_id>/<int:league_id>/<int:season>')
def view_team_stats(team_id, league_id, season):
    """Affiche les statistiques détaillées d'une équipe"""
    try:
        # Récupérer le client API
        api_client = current_app.extensions['api_football']
        
        # Récupérer les données de l'équipe
        team_response = api_client._make_request('teams', {
            'id': team_id
        })
        
        if not team_response or 'response' not in team_response or not team_response['response']:
            flash('Équipe non trouvée', 'warning')
            return redirect(url_for('api_football.index'))
        
        team_data = team_response['response'][0]
        
        # Récupérer les statistiques de l'équipe
        stats_response = api_client._make_request('teams/statistics', {
            'team': team_id,
            'league': league_id,
            'season': season
        })
        
        if not stats_response or 'response' not in stats_response:
            flash('Aucune statistique disponible pour cette équipe', 'warning')
            return redirect(url_for('api_football.index'))
        
        stats_data = stats_response['response']
        
        # Récupérer les matchs à venir de l'équipe
        today = datetime.now().strftime('%Y-%m-%d')
        next_month = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        
        fixtures_response = api_client._make_request('fixtures', {
            'team': team_id,
            'from': today,
            'to': next_month,
            'status': 'NS'
        })
        
        upcoming_matches = []
        if fixtures_response and 'response' in fixtures_response:
            upcoming_matches = fixtures_response['response']
        
        # Formater la saison
        formatted_season = f"{season}/{season+1}"
        
        return render_template('api_football/team_stats.html',
                              team=team_data,
                              stats=stats_data,
                              upcoming_matches=upcoming_matches,
                              season=formatted_season,
                              league_id=league_id)
                              
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des statistiques d'équipe: {str(e)}")
        flash(f"Une erreur s'est produite: {str(e)}", 'danger')
        return redirect(url_for('api_football.index'))

# Nouvelle route pour récupérer et afficher les joueurs d'une équipe
@api_football_bp.route('/team-players/<int:team_id>/<int:season>')
def view_team_players(team_id, season):
    """Affiche les joueurs d'une équipe pour une saison donnée"""
    try:
        # Récupérer le client API
        api_client = current_app.extensions['api_football']
        
        # Récupérer les données de l'équipe
        team_response = api_client._make_request('teams', {
            'id': team_id
        })
        
        if not team_response or 'response' not in team_response or not team_response['response']:
            flash('Équipe non trouvée', 'warning')
            return redirect(url_for('api_football.index'))
        
        team_data = team_response['response'][0]
        
        # Récupérer les joueurs de l'équipe
        players_response = api_client._make_request('players/squads', {
            'team': team_id
        })
        
        if not players_response or 'response' not in players_response or not players_response['response']:
            flash('Aucun joueur disponible pour cette équipe', 'warning')
            return redirect(url_for('api_football.index'))
        
        players_data = players_response['response'][0]['players']
        
        # Récupérer les statistiques des joueurs
        players_stats = []
        for player in players_data:
            stats_response = api_client._make_request('players', {
                'id': player['id'],
                'season': season,
                'team': team_id
            })
            
            if stats_response and 'response' in stats_response and stats_response['response']:
                player_stats = stats_response['response'][0]
                players_stats.append(player_stats)
        
        # Formater la saison
        formatted_season = f"{season}/{season+1}"
        
        return render_template('api_football/team_players.html',
                              team=team_data,
                              players=players_stats,
                              season=formatted_season)
                              
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des joueurs d'équipe: {str(e)}")
        flash(f"Une erreur s'est produite: {str(e)}", 'danger')
        return redirect(url_for('api_football.index'))

# Nouvelle route pour récupérer et afficher les informations d'un joueur
@api_football_bp.route('/player/<int:player_id>/<int:season>')
def view_player(player_id, season):
    """Affiche les informations et statistiques d'un joueur"""
    try:
        # Récupérer le client API
        api_client = current_app.extensions['api_football']
        
        # Récupérer les informations du joueur
        player_response = api_client._make_request('players', {
            'id': player_id,
            'season': season
        })
        
        if not player_response or 'response' not in player_response or not player_response['response']:
            flash('Joueur non trouvé', 'warning')
            return redirect(url_for('api_football.index'))
        
        player_data = player_response['response'][0]
        
        # Récupérer les transferts du joueur
        transfers_response = api_client._make_request('transfers', {
            'player': player_id
        })
        
        transfers_data = []
        if transfers_response and 'response' in transfers_response:
            transfers_data = transfers_response['response']
        
        # Récupérer les trophées du joueur
        trophies_response = api_client._make_request('trophies', {
            'player': player_id
        })
        
        trophies_data = []
        if trophies_response and 'response' in trophies_response:
            trophies_data = trophies_response['response']
        
        # Formater la saison
        formatted_season = f"{season}/{season+1}"
        
        return render_template('api_football/player.html',
                              player=player_data,
                              transfers=transfers_data,
                              trophies=trophies_data,
                              season=formatted_season)
                              
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des informations du joueur: {str(e)}")
        flash(f"Une erreur s'est produite: {str(e)}", 'danger')
        return redirect(url_for('api_football.index'))

# Nouvelle route pour récupérer et afficher les matchs
@api_football_bp.route('/fixtures')
def view_fixtures():
    """Affiche les matchs selon différents critères"""
    try:
        # Récupérer les paramètres
        date = request.args.get('date')
        league_id = request.args.get('league')
        team_id = request.args.get('team')
        status = request.args.get('status', 'all')
        
        # Si aucune date n'est spécifiée, utiliser la date actuelle
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        
        # Préparer les paramètres pour l'API
        params = {}
        
        if date:
            params['date'] = date
        
        if league_id:
            params['league'] = league_id
        
        if team_id:
            params['team'] = team_id
            
        if status != 'all':
            params['status'] = status
        
        # Récupérer le client API
        api_client = current_app.extensions['api_football']
        
        # Récupérer les matchs
        fixtures_response = api_client._make_request('fixtures', params)
        
        if not fixtures_response or 'response' not in fixtures_response:
            flash('Aucun match trouvé pour ces critères', 'warning')
            return redirect(url_for('api_football.index'))
        
        fixtures_data = fixtures_response['response']
        
        # Organiser les matchs par ligue
        fixtures_by_league = {}
        for fixture in fixtures_data:
            league_name = fixture['league']['name']
            league_id = fixture['league']['id']
            league_country = fixture['league']['country']
            league_logo = fixture['league']['logo']
            
            if league_name not in fixtures_by_league:
                fixtures_by_league[league_name] = {
                    'id': league_id,
                    'country': league_country,
                    'logo': league_logo,
                    'fixtures': []
                }
            
            fixtures_by_league[league_name]['fixtures'].append(fixture)
        
        # Si la date est spécifiée, la formater pour l'affichage
        display_date = None
        if date:
            try:
                display_date = datetime.strptime(date, '%Y-%m-%d').strftime('%d/%m/%Y')
            except:
                display_date = date
        
        return render_template('api_football/fixtures.html',
                              fixtures_by_league=fixtures_by_league,
                              date=date,
                              display_date=display_date,
                              league_id=league_id,
                              team_id=team_id,
                              status=status)
                              
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des matchs: {str(e)}")
        flash(f"Une erreur s'est produite: {str(e)}", 'danger')
        return redirect(url_for('api_football.index'))

# Nouvelle route pour récupérer et afficher les détails d'un match
@api_football_bp.route('/fixture/<int:fixture_id>')
def view_fixture(fixture_id):
    """Affiche les détails d'un match"""
    try:
        # Récupérer le client API
        api_client = current_app.extensions['api_football']
        
        # Récupérer les informations du match
        fixture_response = api_client._make_request('fixtures', {
            'id': fixture_id
        })
        
        if not fixture_response or 'response' not in fixture_response or not fixture_response['response']:
            flash('Match non trouvé', 'warning')
            return redirect(url_for('api_football.fixtures'))
        
        fixture_data = fixture_response['response'][0]
        
        # Récupérer les événements du match
        events_response = api_client._make_request('fixtures/events', {
            'fixture': fixture_id
        })
        
        events_data = []
        if events_response and 'response' in events_response:
            events_data = events_response['response']
        
        # Récupérer les statistiques du match
        stats_response = api_client._make_request('fixtures/statistics', {
            'fixture': fixture_id
        })
        
        stats_data = []
        if stats_response and 'response' in stats_response:
            stats_data = stats_response['response']
        
        # Récupérer les compositions d'équipe
        lineups_response = api_client._make_request('fixtures/lineups', {
            'fixture': fixture_id
        })
        
        lineups_data = []
        if lineups_response and 'response' in lineups_response:
            lineups_data = lineups_response['response']
        
        # Récupérer les statistiques des joueurs
        players_response = api_client._make_request('fixtures/players', {
            'fixture': fixture_id
        })
        
        players_data = []
        if players_response and 'response' in players_response:
            players_data = players_response['response']
        
        return render_template('api_football/fixture.html',
                              fixture=fixture_data,
                              events=events_data,
                              stats=stats_data,
                              lineups=lineups_data,
                              players=players_data)
                              
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des détails du match: {str(e)}")
        flash(f"Une erreur s'est produite: {str(e)}", 'danger')
        return redirect(url_for('api_football.fixtures'))