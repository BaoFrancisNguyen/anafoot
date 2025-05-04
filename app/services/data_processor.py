# app/services/data_processor.py
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def process_club_performance(matches):
    """Traite les données de matchs pour générer des statistiques de performance
    
    Args:
        matches: Liste des matchs du club
        
    Returns:
        Un dictionnaire contenant les statistiques de performance
    """
    if not matches:
        return {
            "totalMatches": 0,
            "results": {"wins": 0, "draws": 0, "losses": 0},
            "winPercentage": 0.0,
            "goalsScored": 0,
            "goalsConceded": 0,
            "goalDifference": 0,
            "averageGoalsScored": 0.0,
            "averageGoalsConceded": 0.0,
            "timeline": []
        }
    
    # Initialisation des compteurs
    results = {"wins": 0, "draws": 0, "losses": 0}
    goals_scored = 0
    goals_conceded = 0
    performance_timeline = []
    
    for match in matches:
        # Déterminer si le club est l'équipe à domicile ou à l'extérieur
        is_home = (match.home_team_id == matches[0].home_team_id)
        
        # Calculer les buts marqués et encaissés
        if is_home:
            team_goals = match.home_team_score or 0
            opponent_goals = match.away_team_score or 0
            opponent_name = match.away_team.name if match.away_team else "Équipe inconnue"
        else:
            team_goals = match.away_team_score or 0
            opponent_goals = match.home_team_score or 0
            opponent_name = match.home_team.name if match.home_team else "Équipe inconnue"
        
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
            "date": match.date.strftime('%Y-%m-%d') if match.date else "Date inconnue",
            "opponent": opponent_name,
            "result": result,
            "goalsScored": team_goals,
            "goalsConceded": opponent_goals,
            "isHome": is_home
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
    """Génère des données de carte de chaleur pour un joueur à partir de ses matchs
    
    Args:
        matches: Liste des matchs du joueur
        
    Returns:
        Un dictionnaire contenant les données de la carte de chaleur
    """
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
    # Par défaut, on suppose un milieu de terrain
    position = "midfielder"
    
    if hasattr(matches, 'position'):
        position = matches.position.lower()
    
    if position == "forward" or position == "attaquant":
        # Les attaquants sont plus souvent dans le dernier tiers offensif
        for _ in range(100):
            x = np.random.normal(grid_length * 0.8, grid_length * 0.2)
            y = np.random.normal(grid_width * 0.5, grid_width * 0.3)
            x = max(0, min(int(x), grid_length - 1))
            y = max(0, min(int(y), grid_width - 1))
            heatmap_grid[y, x] += 1
    elif position == "midfielder" or position == "milieu":
        # Les milieux couvrent plus le centre du terrain
        for _ in range(100):
            x = np.random.normal(grid_length * 0.5, grid_length * 0.3)
            y = np.random.normal(grid_width * 0.5, grid_width * 0.3)
            x = max(0, min(int(x), grid_length - 1))
            y = max(0, min(int(y), grid_width - 1))
            heatmap_grid[y, x] += 1
    elif position == "defender" or position == "défenseur":
        # Les défenseurs restent plus dans le tiers défensif
        for _ in range(100):
            x = np.random.normal(grid_length * 0.2, grid_length * 0.2)
            y = np.random.normal(grid_width * 0.5, grid_width * 0.3)
            x = max(0, min(int(x), grid_length - 1))
            y = max(0, min(int(y), grid_width - 1))
            heatmap_grid[y, x] += 1
    elif position == "goalkeeper" or position == "gardien":
        # Les gardiens restent principalement dans la surface de réparation
        for _ in range(100):
            x = np.random.normal(grid_length * 0.05, grid_length * 0.05)
            y = np.random.normal(grid_width * 0.5, grid_width * 0.2)
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

def generate_team_comparison(team1, team2):
    """Génère une comparaison statistique entre deux équipes
    
    Args:
        team1: Premier club à comparer
        team2: Second club à comparer
        
    Returns:
        Un dictionnaire contenant les statistiques comparatives
    """
    # Initialiser le dictionnaire de comparaison
    comparison = {
        "team1": {
            "name": team1.name,
            "stats": {}
        },
        "team2": {
            "name": team2.name,
            "stats": {}
        },
        "categories": ["Buts", "Possession", "Tirs", "Passes", "Duels aériens", "Tacles"]
    }
    
    # Pour l'exemple, nous générons des données fictives
    comparison["team1"]["stats"] = {
        "Buts": 1.8,  # Buts par match
        "Possession": 55,  # Pourcentage
        "Tirs": 14.5,  # Tirs par match
        "Passes": 450,  # Passes par match
        "Duels aériens": 22.3,  # Duels aériens gagnés par match
        "Tacles": 18.7  # Tacles réussis par match
    }
    
    comparison["team2"]["stats"] = {
        "Buts": 1.5,
        "Possession": 52,
        "Tirs": 12.2,
        "Passes": 420,
        "Duels aériens": 19.8,
        "Tacles": 20.1
    }
    
    # Dans une implémentation réelle, ces statistiques seraient calculées à partir des données des matchs
    
    return comparison

def process_player_performance(player, matches):
    """Analyse la performance d'un joueur sur une série de matchs
    
    Args:
        player: Le joueur à analyser
        matches: Liste des matchs joués par le joueur
        
    Returns:
        Un dictionnaire contenant les statistiques de performance
    """
    if not matches:
        return {
            "totalMatches": 0,
            "minutesPlayed": 0,
            "goals": 0,
            "assists": 0,
            "ratings": [],
            "averageRating": 0.0
        }
    
    # Initialiser les compteurs
    total_minutes = 0
    goals = 0
    assists = 0
    ratings = []
    
    # Pour l'exemple, nous générons des données fictives
    for i, match in enumerate(matches):
        # Nombre de minutes jouées (par défaut, supposons qu'il a joué tout le match)
        minutes = 90
        # Note de performance (entre 6.0 et 10.0)
        rating = 6.0 + np.random.rand() * 3.0
        
        total_minutes += minutes
        ratings.append({
            "match": i + 1,
            "opponent": f"Équipe {i+1}",
            "rating": round(rating, 1)
        })
        
        # Simuler des buts et passes décisives occasionnels
        if np.random.rand() < 0.3:  # 30% de chance de marquer
            goals += 1
        if np.random.rand() < 0.2:  # 20% de chance de faire une passe décisive
            assists += 1
    
    return {
        "totalMatches": len(matches),
        "minutesPlayed": total_minutes,
        "goals": goals,
        "assists": assists,
        "ratings": ratings,
        "averageRating": sum(r["rating"] for r in ratings) / len(ratings) if ratings else 0.0
    }

def calculate_player_contribution(player, team):
    """Calcule la contribution d'un joueur aux performances de son équipe
    
    Args:
        player: Le joueur à analyser
        team: L'équipe du joueur
        
    Returns:
        Un pourcentage de contribution
    """
    # Dans une implémentation réelle, ce calcul serait basé sur des statistiques avancées
    # Pour l'exemple, nous utilisons une valeur fixe
    return 15.0  # Pourcentage de contribution