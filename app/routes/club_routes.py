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
    
    # Récupérer les statistiques d'équipe depuis la base de données
    from app.models.team_stats import TeamStats
    stats = TeamStats.query.filter_by(club_id=club.id).order_by(TeamStats.season.desc()).first()
    
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
        # Ajouter des données par défaut pour les statistiques
        "recent_form": [],
        "win_count": 0,
        "draw_count": 0,
        "loss_count": 0,
        "goals_scored": 0,
        "goals_conceded": 0,
        "goal_difference": 0,
        "upcoming_matches": [],
    }
    
    # Si nous avons des statistiques, les ajouter
    if stats:
        club_info["win_count"] = stats.wins
        club_info["draw_count"] = stats.draws
        club_info["loss_count"] = stats.losses
        club_info["goals_scored"] = stats.goals_for
        club_info["goals_conceded"] = stats.goals_against
        club_info["goal_difference"] = stats.goals_for - stats.goals_against
    
    return render_template('club/stats.html', club=club_info)
    

@club_bp.route('/<int:club_id>/performance')
def club_performance(club_id):
    """Renvoie les données de performance d'un club au format JSON pour les graphiques"""
    try:
        # Récupérer les statistiques d'équipe depuis la base de données
        from app.models.team_stats import TeamStats
        stats = TeamStats.query.filter_by(club_id=club_id).order_by(TeamStats.season.desc()).first()
        
        if stats:
            # Construire les données de performance
            performance_data = {
                "totalMatches": stats.matches_played,
                "results": {
                    "wins": stats.wins,
                    "draws": stats.draws,
                    "losses": stats.losses
                },
                "winPercentage": round((stats.wins / stats.matches_played * 100), 2) if stats.matches_played > 0 else 0,
                "goalsScored": stats.goals_for,
                "goalsConceded": stats.goals_against,
                "goalDifference": stats.goals_for - stats.goals_against,
                "averageGoalsScored": round((stats.goals_for / stats.matches_played), 2) if stats.matches_played > 0 else 0,
                "averageGoalsConceded": round((stats.goals_against / stats.matches_played), 2) if stats.matches_played > 0 else 0,
                "timeline": [],  # Données fictives pour l'instant
                "averagePossession": 50,  # Données fictives pour le graphique radar
                "passAccuracy": 75,
                "duelsWonPercentage": 50,
                "tacklesPerMatch": 15
            }
            return jsonify(performance_data)
        else:
            # Si aucune statistique n'est disponible, retourner des données fictives
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
                "averagePossession": 50,
                "passAccuracy": 75,
                "duelsWonPercentage": 50,
                "tacklesPerMatch": 15
            })
    except Exception as e:
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