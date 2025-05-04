# app/routes/player_routes.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from app.models.player import Player
from app.models.player_stats import PlayerStats  # Ajouté pour le débogage
from app.services.data_fetcher import get_player_stats, get_player_matches
from app.services.data_processor import process_player_heatmap, process_player_performance
from app import db
import logging
import sys  # Ajouté pour le débogage
import traceback  # Ajouté pour le débogage

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
    try:
        # Débogage: Vérifier si le joueur existe
        print(f"Recherche du joueur avec ID: {player_id}")
        player = Player.query.get_or_404(player_id)
        print(f"Joueur trouvé: {player.name}, position: {player.position}")
        
        # Débogage: Vérifier directement si des statistiques existent
        stats_records = PlayerStats.query.filter_by(player_id=player_id).all()
        print(f"Nombre de statistiques trouvées: {len(stats_records)}")
        for stat in stats_records:
            print(f"Statistiques de la saison {stat.season}: matches_played={stat.matches_played}, goals={stat.goals}")
        
        # Créer un dictionnaire avec les informations de base et des statistiques par défaut
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
            }
        }
        
        # Méthode 1: Utiliser la méthode de classe si elle existe
        if hasattr(player, 'get_current_season_stats') and callable(getattr(player, 'get_current_season_stats')):
            print("Méthode get_current_season_stats trouvée, tentative d'utilisation...")
            try:
                stats = player.get_current_season_stats()
                print(f"Statistiques via méthode de classe: {stats}")
                if stats:
                    player_info["stats"] = stats
            except Exception as e:
                print(f"Erreur lors de l'utilisation de get_current_season_stats: {str(e)}")
                print(traceback.format_exc())
        
        # Méthode 2: Utilisation directe des statistiques récentes
        if len(stats_records) > 0:
            print("Tentative d'utilisation directe des statistiques...")
            # Prendre les statistiques les plus récentes (basées sur la saison)
            recent_stats = stats_records[0]  # On suppose que la première est la plus récente
            
            # Convertir l'objet en dictionnaire
            stats_dict = {}
            for attr in dir(recent_stats):
                # Exclure les attributs privés et les méthodes
                if not attr.startswith('_') and not callable(getattr(recent_stats, attr)):
                    stats_dict[attr] = getattr(recent_stats, attr)
            
            print(f"Statistiques reconstruites: {stats_dict}")
            player_info["stats"] = stats_dict
        
        print(f"Données du joueur finales: {player_info}")
        return render_template('player/stats.html', player=player_info)
        
    except Exception as e:
        print(f"ERREUR CRITIQUE: {str(e)}")
        print(traceback.format_exc())
        flash(f"Une erreur s'est produite: {str(e)}", "danger")
        return redirect(url_for('player.index'))

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