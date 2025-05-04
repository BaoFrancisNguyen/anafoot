# app/routes/club_routes.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from app.models.club import Club
from app.models.match import Match
from app.services.data_fetcher import get_club_stats, get_club_matches
from app.services.data_processor import process_club_performance
from app import db
import logging

logger = logging.getLogger(__name__)

# Création du Blueprint
club_bp = Blueprint('club', __name__)

@club_bp.route('/')
def index():
    """Liste des clubs"""
    clubs = Club.query.all()
    return render_template('club/index.html', clubs=clubs)

@club_bp.route('/search')
def search():
    """Recherche de clubs"""
    query = request.args.get('q', '')
    if query:
        clubs = Club.query.filter(Club.name.ilike(f'%{query}%')).all()
    else:
        clubs = []
    return render_template('club/search.html', clubs=clubs, query=query)

# Version modifiée de la fonction club_stats
@club_bp.route('/<int:club_id>')
def club_stats(club_id):
    """Affiche les statistiques d'un club"""
    # Récupérer le club directement depuis la base de données
    club = Club.query.get_or_404(club_id)
    
    # Créer un objet avec les informations de base du club
    club_info = {
        "id": club.id,
        "name": club.name,
        "short_name": club.short_name,
        "tla": club.tla,
        "crest": club.crest,
        "venue": club.venue,
        "founded": club.founded,
        "website": club.website,
        # Ajouter des données fictives pour les statistiques
        "recent_form": [],
        "win_count": 0,
        "draw_count": 0,
        "loss_count": 0,
        "goals_scored": 0,
        "goals_conceded": 0,
        "goal_difference": 0,
        "upcoming_matches": [],
        # Plus d'attributs si nécessaire
    }
    
    # Essayer d'obtenir les statistiques réelles, si disponibles
    try:
        api_stats = get_club_stats(club_id)
        if api_stats:
            # Mettre à jour avec les données réelles
            club_info.update(api_stats)
    except Exception as e:
        # En cas d'erreur, logger et continuer avec les données de base
        print(f"Erreur lors de la récupération des statistiques: {str(e)}")
        flash(f"Impossible de récupérer toutes les statistiques. Affichage des informations de base uniquement.", "warning")
    
    return render_template('club/stats.html', club=club_info)
    

@club_bp.route('/<int:club_id>/performance')
def club_performance(club_id):
    """Renvoie les données de performance d'un club au format JSON pour les graphiques"""
    try:
        # Essayer d'abord d'obtenir les matches via l'API
        matches = get_club_matches(club_id)
        if matches:
            performance_data = process_club_performance(matches)
            return jsonify(performance_data)
        
        # Si aucun match n'est disponible via l'API, essayez la base de données
        club = Club.query.get_or_404(club_id)
        db_matches = club.get_all_matches()
        if db_matches:
            performance_data = process_club_performance(db_matches)
            return jsonify(performance_data)
        
        # Si toujours aucun match, retournez des données fictives
        return jsonify({
            "totalMatches": 0,
            "results": {"wins": 0, "draws": 0, "losses": 0},
            "winPercentage": 0,
            "goalsScored": 0,
            "goalsConceded": 0,
            "goalDifference": 0,
            "averageGoalsScored": 0,
            "averageGoalsConceded": 0,
            "timeline": [],
            "averagePossession": 50,  # données fictives pour le graphique radar
            "passAccuracy": 75,
            "duelsWonPercentage": 50,
            "tacklesPerMatch": 15
        })
    except Exception as e:
        # En cas d'erreur, renvoyer des données de base
        print(f"Erreur lors de la récupération des données de performance: {str(e)}")
        return jsonify({
            "error": str(e),
            "totalMatches": 0,
            "results": {"wins": 0, "draws": 0, "losses": 0},
            "timeline": []
        })

@club_bp.route('/<int:club_id>/matches')
def club_matches(club_id):
    """Affiche les matchs d'un club"""
    club = Club.query.get_or_404(club_id)
    season = request.args.get('season')
    
    matches = get_club_matches(club_id, season)
    
    return render_template('club/matches.html', club=club, matches=matches, season=season)

@club_bp.route('/<int:club_id>/players')
def club_players(club_id):
    """Affiche les joueurs d'un club"""
    club = Club.query.get_or_404(club_id)
    return render_template('club/players.html', club=club)