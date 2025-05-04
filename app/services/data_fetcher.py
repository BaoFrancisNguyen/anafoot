# app/services/data_fetcher.py
import requests
import pandas as pd
import os
from flask import current_app

def get_football_api_data(endpoint, params=None):
    """Récupère les données depuis une API de football"""
    api_key = current_app.config['FOOTBALL_API_KEY']
    base_url = "https://api.football-data.org/v4"
    
    headers = {
        "X-Auth-Token": api_key
    }
    
    response = requests.get(f"{base_url}/{endpoint}", headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        # Gestion des erreurs
        print(f"Erreur API: {response.status_code} - {response.text}")
        return None

def import_csv_data(file_path):
    """Importe des données depuis un fichier CSV"""
    try:
        df = pd.read_csv(file_path)
        return df
    except Exception as e:
        print(f"Erreur lors de l'importation du CSV: {e}")
        return None

def get_club_stats(club_id):
    """Récupère les statistiques d'un club"""
    # Exemple utilisant l'API
    team_data = get_football_api_data(f"teams/{club_id}")
    
    # Récupération des 20 derniers matchs
    matches = get_football_api_data("matches", {"team": club_id, "limit": 20})
    
    # Traitement des données pour créer un objet avec les statistiques du club
    if team_data and matches:
        stats = {
            "id": team_data["id"],
            "name": team_data["name"],
            "crest": team_data["crest"],
            "founded": team_data.get("founded"),
            "venue": team_data.get("venue"),
            "coach": team_data.get("coach", {}).get("name"),
            "matches": matches["matches"],
            # D'autres statistiques calculées à partir des matchs peuvent être ajoutées ici
        }
        return stats
    return None

def get_club_matches(club_id, season=None):
    """Récupère les matchs d'un club pour une saison donnée"""
    params = {"team": club_id, "limit": 100}
    if season:
        params["season"] = season
        
    matches_data = get_football_api_data("matches", params)
    
    if matches_data:
        return matches_data["matches"]
    return []

def get_player_stats(player_id):
    """Récupère les statistiques d'un joueur"""
    player_data = get_football_api_data(f"players/{player_id}")
    
    if player_data:
        # Récupérer les statistiques du joueur pour la saison en cours
        current_season = player_data.get("currentSeason", {}).get("id")
        if current_season:
            stats_data = get_football_api_data(f"players/{player_id}/stats", {"season": current_season})
            
            player_info = {
                "id": player_data["id"],
                "name": player_data["name"],
                "position": player_data.get("position"),
                "dateOfBirth": player_data.get("dateOfBirth"),
                "nationality": player_data.get("nationality"),
                "stats": stats_data
            }
            return player_info
    return None

def get_player_matches(player_id, limit=10):
    """Récupère les derniers matchs d'un joueur avec ses statistiques individuelles"""
    # Cette fonction dépend de la structure de l'API utilisée
    # Simulons des données pour l'exemple
    player_matches = []
    # Dans une vraie implémentation, récupérez les données depuis l'API
    return player_matches

# app/services/data_processor.py
import pandas as pd
import numpy as np

def process_club_performance(matches):
    """Traite les données de matchs pour générer des statistiques de performance"""
    if not matches:
        return {}
    
    # Initialisation des compteurs
    results = {"wins": 0, "draws": 0, "losses": 0}
    goals_scored = 0
    goals_conceded = 0
    performance_timeline = []
    
    for match in matches:
        # Déterminer si le club est l'équipe à domicile ou à l'extérieur
        is_home = (match["homeTeam"]["id"] == matches[0]["homeTeam"]["id"])
        
        # Calculer les buts marqués et encaissés
        if is_home:
            team_goals = match["score"]["fullTime"]["home"] or 0
            opponent_goals = match["score"]["fullTime"]["away"] or 0
        else:
            team_goals = match["score"]["fullTime"]["away"] or 0
            opponent_goals = match["score"]["fullTime"]["home"] or 0
        
        goals_scored += team_goals
        goals_conceded += opponent_goals
        
        # Déterminer le résultat
        if team_goals > opponent_goals:
            results["wins"] += 1
            result = "W"
        elif team_goals < opponent_goals:
            results["losses"] += 1
            result = "L"
        else:
            results["draws"] += 1
            result = "D"
        
        # Ajouter au timeline
        performance_timeline.append({
            "date": match["utcDate"],
            "opponent": match["homeTeam"]["name"] if not is_home else match["awayTeam"]["name"],
            "result": result,
            "goalsScored": team_goals,
            "goalsConceded": opponent_goals
        })
    
    # Calculer des statistiques supplémentaires
    total_matches = len(matches)
    win_percentage = (results["wins"] / total_matches) * 100 if total_matches > 0 else 0
    
    return {
        "totalMatches": total_matches,
        "results": results,
        "winPercentage": win_percentage,
        "goalsScored": goals_scored,
        "goalsConceded": goals_conceded,
        "goalDifference": goals_scored - goals_conceded,
        "averageGoalsScored": goals_scored / total_matches if total_matches > 0 else 0,
        "averageGoalsConceded": goals_conceded / total_matches if total_matches > 0 else 0,
        "timeline": performance_timeline
    }

def process_player_heatmap(matches):
    """Génère des données de carte de chaleur pour un joueur à partir de ses matchs"""
    # Cette fonction nécessite des données de position détaillées pour chaque match
    # Pour l'exemple, nous allons générer des données simulées
    
    # Dimensions standard d'un terrain de football (en mètres)
    pitch_length = 105
    pitch_width = 68
    
    # Créer une grille 2D pour représenter le terrain
    grid_size = 10  # Taille des cellules de la grille en mètres
    grid_length = int(pitch_length / grid_size)
    grid_width = int(pitch_width / grid_size)
    
    # Initialiser la grille avec des zéros
    heatmap_grid = np.zeros((grid_width, grid_length))
    
    # Dans une vraie implémentation, vous analyseriez les données réelles des matchs
    # Pour l'exemple, nous générons des données simulées basées sur la position du joueur
    
    # Simuler quelques positions fréquentes pour un joueur (dépend de son poste)
    position = "midfielder"  # À remplacer par la position réelle du joueur
    
    if position == "forward":
        # Les attaquants sont plus souvent dans le dernier tiers offensif
        for _ in range(100):
            x = np.random.normal(grid_length * 0.8, grid_length * 0.2)
            y = np.random.normal(grid_width * 0.5, grid_width * 0.3)
            x = max(0, min(int(x), grid_length - 1))
            y = max(0, min(int(y), grid_width - 1))
            heatmap_grid[y, x] += 1
    elif position == "midfielder":
        # Les milieux couvrent plus le centre du terrain
        for _ in range(100):
            x = np.random.normal(grid_length * 0.5, grid_length * 0.3)
            y = np.random.normal(grid_width * 0.5, grid_width * 0.3)
            x = max(0, min(int(x), grid_length - 1))
            y = max(0, min(int(y), grid_width - 1))
            heatmap_grid[y, x] += 1
    elif position == "defender":
        # Les défenseurs restent plus dans le tiers défensif
        for _ in range(100):
            x = np.random.normal(grid_length * 0.2, grid_length * 0.2)
            y = np.random.normal(grid_width * 0.5, grid_width * 0.3)
            x = max(0, min(int(x), grid_length - 1))
            y = max(0, min(int(y), grid_width - 1))
            heatmap_grid[y, x] += 1
    
    # Convertir la grille en format pour la visualisation
    heatmap_data = []
    for y in range(grid_width):
        for x in range(grid_length):
            if heatmap_grid[y, x] > 0:
                heatmap_data.append({
                    "x": x * grid_size,
                    "y": y * grid_size,
                    "value": float(heatmap_grid[y, x])
                })
    
    return {
        "heatmapData": heatmap_data,
        "pitchDimensions": {
            "length": pitch_length,
            "width": pitch_width
        }
    }