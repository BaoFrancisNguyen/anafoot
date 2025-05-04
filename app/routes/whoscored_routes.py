# app/routes/whoscored_routes.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from app.services.whoscored_data_fetcher import WhoScoredDataFetcher
from app.services.whoscored_scraper import WhoScoredSeleniumScraper
from app.models.club import Club
from app.models.player import Player
from app.models.match import Match
from app.models.player_stats import PlayerStats
from app import db
from datetime import datetime
import logging
import json
import os
import pandas as pd
from io import StringIO
import csv

# Configuration du logger
logger = logging.getLogger(__name__)

# Création du Blueprint
whoscored_bp = Blueprint('whoscored', __name__)

# Mapping des identifiants de ligues pour l'interface utilisateur
LEAGUE_MAPPING = {
    'premier_league': {'id': '252/2', 'name': 'Premier League', 'country': 'Angleterre'},
    'la_liga': {'id': '206/4', 'name': 'La Liga', 'country': 'Espagne'},
    'serie_a': {'id': '108/5', 'name': 'Serie A', 'country': 'Italie'},
    'bundesliga': {'id': '81/3', 'name': 'Bundesliga', 'country': 'Allemagne'},
    'ligue_1': {'id': '74/22', 'name': 'Ligue 1', 'country': 'France'}
}

@whoscored_bp.route('/')
def index():
    """Page d'accueil de l'import WhoScored"""
    return render_template('whoscored/index.html', leagues=LEAGUE_MAPPING)

@whoscored_bp.route('/import', methods=['GET', 'POST'])
def import_data():
    """Formulaire d'import des données depuis WhoScored"""
    if request.method == 'POST':
        league_id = request.form.get('league')
        season_id = request.form.get('season')
        import_type = request.form.get('import_type')
        
        # Récupérer les options Selenium
        headless = 'headless' not in request.form  # Inversé pour correspondre à la logique du formulaire
        chrome_path = request.form.get('chrome_path') or None
        
        try:
            # Utiliser le scraper Selenium pour toutes les requêtes
            scraper = WhoScoredSeleniumScraper(headless=headless, chrome_path=chrome_path)
            if import_type == 'teams':
                # Import des équipes
                
                teams = scraper.get_league_teams(league_id, season_id)
                
                # Enregistrer les équipes en base de données
                for team in teams:
                    db_team = Club.query.filter_by(api_id=team['id']).first()
                    
                    if not db_team:
                        db_team = Club(
                            api_id=team['id'],
                            name=team['name'],
                            short_name=team['name'],
                            # Autres champs...
                        )
                        db.session.add(db_team)
                
                db.session.commit()
                flash(f'{len(teams)} équipes importées avec succès', 'success')
                
            elif import_type == 'players':
                # Import des joueurs pour toutes les équipes de la ligue
                fetcher = WhoScoredDataFetcher(proxy=proxy)
                teams = fetcher.get_league_teams(league_id, season_id)
                
                total_players = 0
                for team in teams:
                    players = fetcher.get_team_players(team['id'], season_id)
                    
                    # Récupérer l'ID de l'équipe dans notre base de données
                    db_team = Club.query.filter_by(api_id=team['id']).first()
                    
                    if not db_team:
                        # L'équipe n'existe pas, on la crée
                        db_team = Club(
                            api_id=team['id'],
                            name=team['name'],
                            short_name=team['name'],
                            # Autres champs...
                        )
                        db.session.add(db_team)
                        db.session.commit()
                    
                    # Enregistrer les joueurs
                    for player in players:
                        db_player = Player.query.filter_by(api_id=player['id']).first()
                        
                        if not db_player:
                            db_player = Player(
                                api_id=player['id'],
                                name=player['name'],
                                position=player['position'],
                                club_id=db_team.id
                                # Autres champs...
                            )
                            db.session.add(db_player)
                    
                    db.session.commit()
                    total_players += len(players)
                
                flash(f'{total_players} joueurs importés avec succès', 'success')
                
            elif import_type == 'player_stats':
                # Import des statistiques des joueurs
                if 'headless' in request.form:
                    headless = False
                else:
                    headless = True
                
                chrome_path = request.form.get('chrome_path') or None
                
                # Utiliser Selenium pour récupérer les statistiques détaillées
                scraper = WhoScoredSeleniumScraper(headless=headless, chrome_path=chrome_path)
                
                # Récupérer la liste des joueurs à traiter
                players = Player.query.join(Club).filter(Club.api_id.in_([team['id'] for team in fetcher.get_league_teams(league_id, season_id)])).all()
                
                stats_count = 0
                for player in players:
                    if player.api_id:
                        stats = scraper.get_player_detailed_stats(player.api_id, season_id)
                        
                        if stats:
                            # Créer ou mettre à jour les statistiques du joueur
                            db_stats = PlayerStats.query.filter_by(
                                player_id=player.id,
                                season=season_id
                            ).first()
                            
                            if not db_stats:
                                db_stats = PlayerStats(
                                    player_id=player.id,
                                    season=season_id
                                )
                                db.session.add(db_stats)
                            
                            # Mettre à jour les statistiques
                            update_player_stats_from_whoscored(db_stats, stats)
                            db.session.commit()
                            stats_count += 1
                
                flash(f'Statistiques de {stats_count} joueurs importées avec succès', 'success')
                
            elif import_type == 'league_stats':
                # Import des statistiques d'une ligue entière pour une catégorie spécifique
                category = request.form.get('stats_category') or 'Summary'
                
                if 'headless' in request.form:
                    headless = False
                else:
                    headless = True
                
                chrome_path = request.form.get('chrome_path') or None
                
                # Utiliser Selenium pour récupérer les statistiques de la ligue
                scraper = WhoScoredSeleniumScraper(headless=headless, chrome_path=chrome_path)
                
                # Récupérer les statistiques
                df = scraper.get_league_player_statistics(league_id, season_id, category)
                
                if df is not None:
                    # Sauvegarder les données dans un fichier CSV temporaire
                    csv_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'temp', f'league_{league_id}_{season_id}_{category.lower()}.csv')
                    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
                    
                    df.to_csv(csv_path, index=False)
                    
                    flash(f'Statistiques {category} de la ligue importées avec succès', 'success')
                    return redirect(url_for('whoscored.view_league_stats', league_id=league_id, season_id=season_id, category=category.lower()))
                else:
                    flash('Erreur lors de la récupération des statistiques de la ligue', 'danger')
            
            else:
                flash('Type d\'import non reconnu', 'danger')
                
        except Exception as e:
            logger.error(f"Erreur lors de l'import des données: {str(e)}")
            flash(f'Erreur lors de l\'import des données: {str(e)}', 'danger')
            db.session.rollback()
        
        return redirect(url_for('whoscored.import_data'))
    
    # GET request - afficher le formulaire
    return render_template('whoscored/import.html', leagues=LEAGUE_MAPPING)

@whoscored_bp.route('/view/league/<league_id>/<season_id>/<category>')
def view_league_stats(league_id, season_id, category):
    """Affiche les statistiques de la ligue importées"""
    csv_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'temp', f'league_{league_id}_{season_id}_{category}.csv')
    
    if not os.path.exists(csv_path):
        flash('Données non disponibles - veuillez d\'abord importer les statistiques', 'warning')
        return redirect(url_for('whoscored.import_data'))
    
    # Lire le fichier CSV
    df = pd.read_csv(csv_path)
    
    # Convertir en HTML pour l'affichage
    table_html = df.to_html(classes='table table-striped table-hover', index=False)
    
    # Déterminer le nom de la ligue
    league_name = "Ligue inconnue"
    for key, value in LEAGUE_MAPPING.items():
        if value['id'] == league_id:
            league_name = value['name']
            break
    
    return render_template('whoscored/view_league_stats.html', 
                          table_html=table_html, 
                          league_name=league_name, 
                          season_id=season_id, 
                          category=category.capitalize())

@whoscored_bp.route('/view/player/<int:player_id>')
def view_player_stats(player_id):
    """Affiche les statistiques détaillées d'un joueur"""
    player = Player.query.get_or_404(player_id)
    stats = PlayerStats.query.filter_by(player_id=player_id).all()
    
    return render_template('whoscored/view_player_stats.html', player=player, stats=stats)

@whoscored_bp.route('/upload/csv', methods=['GET', 'POST'])
def upload_csv():
    """Import des données à partir d'un fichier CSV"""
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('Aucun fichier sélectionné', 'danger')
            return redirect(request.url)
        
        file = request.files['csv_file']
        
        if file.filename == '':
            flash('Aucun fichier sélectionné', 'danger')
            return redirect(request.url)
        
        if file:
            # Vérifier l'extension du fichier
            if not file.filename.endswith('.csv'):
                flash('Le fichier doit être au format CSV', 'danger')
                return redirect(request.url)
            
            # Lire le contenu du CSV
            content = file.read().decode('utf-8')
            csv_data = StringIO(content)
            reader = csv.DictReader(csv_data)
            
            # Déterminer le type de données
            data_type = request.form.get('data_type')
            
            if data_type == 'player_stats':
                # Import des statistiques des joueurs
                import_player_stats_from_csv(reader)
                flash('Statistiques des joueurs importées avec succès', 'success')
            elif data_type == 'matches':
                # Import des matchs
                import_matches_from_csv(reader)
                flash('Matchs importés avec succès', 'success')
            else:
                flash('Type de données non reconnu', 'danger')
            
            return redirect(url_for('whoscored.index'))
    
    return render_template('whoscored/upload_csv.html')

def update_player_stats_from_whoscored(db_stats, stats):
    """
    Met à jour les statistiques d'un joueur dans la base de données
    à partir des données extraites de WhoScored
    
    Args:
        db_stats: l'objet PlayerStats à mettre à jour
        stats: les statistiques extraites de WhoScored
    """
    # Statistiques générales/résumé
    if 'summary' in stats:
        for key, value in stats['summary'].items():
            # Convertir les clés WhoScored vers les noms de champs de notre modèle
            field_name = convert_whoscored_field_name(key)
            if hasattr(db_stats, field_name):
                setattr(db_stats, field_name, value)
    
    # Statistiques offensives
    if 'offensive' in stats:
        if 'goals' in stats['offensive']:
            db_stats.goals = stats['offensive']['goals']
        if 'assists' in stats['offensive']:
            db_stats.assists = stats['offensive']['assists']
        if 'shots_per_game' in stats['offensive']:
            db_stats.shots = float(stats['offensive']['shots_per_game']) * db_stats.matches_played
        if 'shots_on_target_per_game' in stats['offensive']:
            db_stats.shots_on_target = float(stats['offensive']['shots_on_target_per_game']) * db_stats.matches_played
    
    # Statistiques défensives
    if 'defensive' in stats:
        if 'tackles_per_game' in stats['defensive']:
            db_stats.tackles = float(stats['defensive']['tackles_per_game']) * db_stats.matches_played
        if 'interceptions_per_game' in stats['defensive']:
            db_stats.interceptions = float(stats['defensive']['interceptions_per_game']) * db_stats.matches_played
        if 'clearances_per_game' in stats['defensive']:
            db_stats.clearances = float(stats['defensive']['clearances_per_game']) * db_stats.matches_played
    
    # Statistiques de passes
    if 'passing' in stats:
        if 'passes_per_game' in stats['passing']:
            db_stats.passes = float(stats['passing']['passes_per_game']) * db_stats.matches_played
        if 'pass_success_percentage' in stats['passing']:
            db_stats.passes_completed = int(db_stats.passes * float(stats['passing']['pass_success_percentage']) / 100)
        if 'key_passes_per_game' in stats['passing']:
            db_stats.key_passes = float(stats['passing']['key_passes_per_game']) * db_stats.matches_played
    
    # Mettre à jour la date de mise à jour
    db_stats.updated_at = datetime.utcnow()

def convert_whoscored_field_name(whoscored_field):
    """
    Convertit un nom de champ WhoScored en nom de champ pour notre modèle
    
    Args:
        whoscored_field: le nom du champ dans WhoScored
        
    Returns:
        Le nom du champ correspondant dans notre modèle
    """
    mapping = {
        'apps': 'matches_played',
        'mins_played': 'minutes_played',
        'goals': 'goals',
        'assists': 'assists',
        'yellow_cards': 'yellow_cards',
        'red_cards': 'red_cards',
        'shots_per_game': 'shots',
        'pass_success': 'pass_accuracy',
        'aerials_won': 'duels_won',
        'man_of_the_match': 'motm',
        'rating': 'rating'
    }
    
    return mapping.get(whoscored_field, whoscored_field)

def import_player_stats_from_csv(csv_reader):
    """
    Importe les statistiques des joueurs à partir d'un fichier CSV
    
    Args:
        csv_reader: Un objet csv.DictReader contenant les données
    """
    for row in csv_reader:
        # Vérifier si le joueur existe
        player_name = row.get('Player')
        team_name = row.get('Team')
        
        if not player_name or not team_name:
            continue
        
        # Rechercher le club
        club = Club.query.filter_by(name=team_name).first()
        
        if not club:
            # Créer le club s'il n'existe pas
            club = Club(name=team_name, short_name=team_name)
            db.session.add(club)
            db.session.commit()
        
        # Rechercher le joueur
        player = Player.query.filter_by(name=player_name, club_id=club.id).first()
        
        if not player:
            # Créer le joueur s'il n'existe pas
            player = Player(
                name=player_name,
                club_id=club.id,
                position=row.get('Position', 'Unknown')
            )
            db.session.add(player)
            db.session.commit()
        
        # Récupérer ou créer les statistiques
        season = row.get('Season', '2023/2024')  # Saison par défaut
        
        stats = PlayerStats.query.filter_by(player_id=player.id, season=season).first()
        
        if not stats:
            stats = PlayerStats(player_id=player.id, season=season)
            db.session.add(stats)
        
        # Mettre à jour les statistiques
        for key, value in row.items():
            field_name = convert_whoscored_field_name(key.lower().replace(' ', '_'))
            
            if hasattr(stats, field_name) and value:
                # Convertir la valeur selon le type attendu
                try:
                    if isinstance(getattr(stats, field_name), int):
                        setattr(stats, field_name, int(value))
                    elif isinstance(getattr(stats, field_name), float):
                        setattr(stats, field_name, float(value))
                    else:
                        setattr(stats, field_name, value)
                except (ValueError, TypeError):
                    # Ignorer les erreurs de conversion
                    pass
        
        stats.updated_at = datetime.utcnow()
    
    db.session.commit()

def import_matches_from_csv(csv_reader):
    """
    Importe les matchs à partir d'un fichier CSV
    
    Args:
        csv_reader: Un objet csv.DictReader contenant les données
    """
    for row in csv_reader:
        # Vérifier les données minimales
        home_team_name = row.get('HomeTeam')
        away_team_name = row.get('AwayTeam')
        match_date_str = row.get('Date')
        
        if not home_team_name or not away_team_name or not match_date_str:
            continue
        
        # Convertir la date
        try:
            match_date = datetime.strptime(match_date_str, '%Y-%m-%d')
        except ValueError:
            try:
                match_date = datetime.strptime(match_date_str, '%d/%m/%Y')
            except ValueError:
                continue  # Ignorer si le format de date n'est pas reconnu
        
        # Récupérer ou créer les équipes
        home_team = Club.query.filter_by(name=home_team_name).first()
        if not home_team:
            home_team = Club(name=home_team_name, short_name=home_team_name)
            db.session.add(home_team)
            db.session.commit()
        
        away_team = Club.query.filter_by(name=away_team_name).first()
        if not away_team:
            away_team = Club(name=away_team_name, short_name=away_team_name)
            db.session.add(away_team)
            db.session.commit()
        
        # Récupérer les scores
        home_score = int(row.get('FTHG', 0))  # Full Time Home Goals
        away_score = int(row.get('FTAG', 0))  # Full Time Away Goals
        
        # Vérifier si le match existe déjà
        match = Match.query.filter_by(
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            date=match_date
        ).first()
        
        if not match:
            # Créer le match
            match = Match(
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                date=match_date,
                home_team_score=home_score,
                away_team_score=away_score,
                status='FINISHED',
                competition=row.get('League', 'Unknown'),
                season=row.get('Season', '2023/2024')
            )
            db.session.add(match)
        else:
            # Mettre à jour le match existant
            match.home_team_score = home_score
            match.away_team_score = away_score
            match.status = 'FINISHED'
    
    db.session.commit()