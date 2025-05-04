# app/routes/player_routes.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from app.models.player import Player
from app.services.data_fetcher import get_player_stats, get_player_matches
from app.services.data_processor import process_player_heatmap, process_player_performance
from app import db
import logging

logger = logging.getLogger(__name__)

# Création du Blueprint
player_bp = Blueprint('player', __name__)

@player_bp.route('/')
def index():
    """Liste des joueurs"""
    players = Player.query.limit(50).all()  # Limiter à 50 joueurs pour la performance
    return render_template('player/index.html', players=players)

@player_bp.route('/search')
def search():
    """Recherche de joueurs"""
    query = request.args.get('q', '')
    if query:
        players = Player.query.filter(Player.name.ilike(f'%{query}%')).all()
    else:
        players = []
    return render_template('player/search.html', players=players, query=query)

@player_bp.route('/<int:player_id>')
def player_stats(player_id):
    """Affiche les statistiques d'un joueur"""
    # Récupérer directement le joueur depuis la base de données
    player = Player.query.get_or_404(player_id)
    
    # Créer un dictionnaire avec les informations de base et des statistiques fictives
    player_info = {
        "id": player.id,
        "name": player.name,
        "position": player.position,
        "api_id": player.api_id,
        "photo_url": player.photo_url,
        "nationality": player.nationality,
        "date_of_birth": player.date_of_birth,
        "current_club": player.club,
        "stats": {
            "matches_played": 0, 
            "minutes_played": 0,
            "goals": 0,
            "assists": 0,
            "yellow_cards": 0,
            "red_cards": 0
            # Autres statistiques
        }
    }
    
    # Essayer d'obtenir les statistiques réelles si disponibles
    try:
        stats = player.get_current_season_stats()
        if stats and not isinstance(stats, dict):
            # Convertir l'objet stats en dictionnaire si c'est un objet
            stats_dict = {}
            for attr in dir(stats):
                if not attr.startswith('_') and not callable(getattr(stats, attr)):
                    stats_dict[attr] = getattr(stats, attr)
            player_info["stats"] = stats_dict
        elif stats and isinstance(stats, dict):
            player_info["stats"] = stats
    except Exception as e:
        print(f"Erreur lors de la récupération des statistiques: {str(e)}")
        flash("Impossible de récupérer toutes les statistiques.", "warning")
    
    return render_template('player/stats.html', player=player_info)

@player_bp.route('/<int:player_id>/heatmap')
def player_heatmap(player_id):
    """Renvoie les données pour la carte de chaleur du positionnement du joueur"""
    player = Player.query.get_or_404(player_id)
    heatmap_data = process_player_heatmap(player)
    return jsonify(heatmap_data)

@player_bp.route('/<int:player_id>/performance')
def player_performance(player_id):
    """Renvoie les données de performance d'un joueur pour les graphiques"""
    player = Player.query.get_or_404(player_id)
    matches = get_player_matches(player_id, limit=10)
    performance_data = process_player_performance(player, matches)
    return jsonify(performance_data)

@player_bp.route('/compare/<int:player1_id>/<int:player2_id>')
def compare_players(player1_id, player2_id):
    """Compare deux joueurs"""
    player1 = Player.query.get_or_404(player1_id)
    player2 = Player.query.get_or_404(player2_id)
    
    # Récupérer les statistiques des deux joueurs
    player1_stats = get_player_stats(player1_id)
    player2_stats = get_player_stats(player2_id)
    
    return render_template('player/compare.html', 
                          player1=player1, 
                          player2=player2,
                          player1_stats=player1_stats,
                          player2_stats=player2_stats)