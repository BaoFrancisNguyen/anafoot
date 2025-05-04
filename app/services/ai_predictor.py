# app/services/ai_predictor.py
import requests
import json
import pandas as pd
from flask import current_app
from app.services.data_fetcher import get_club_stats, get_club_matches

def prepare_match_data(home_team_id, away_team_id, match_date):
    """Prépare les données pour la prédiction de match"""
    # Récupérer les statistiques des équipes
    home_stats = get_club_stats(home_team_id)
    away_stats = get_club_stats(away_team_id)
    
    # Récupérer l'historique des confrontations
    home_matches = get_club_matches(home_team_id)
    away_matches = get_club_matches(away_team_id)
    
    # Préparer les statistiques récentes
    home_recent_form = process_recent_form(home_matches, home_team_id)
    away_recent_form = process_recent_form(away_matches, away_team_id)
    
    # Trouver les confrontations directes
    head_to_head = find_head_to_head(home_matches, away_team_id)
    
    # Compiler toutes les données
    match_data = {
        "home_team": {
            "name": home_stats["name"],
            "recent_form": home_recent_form
        },
        "away_team": {
            "name": away_stats["name"],
            "recent_form": away_recent_form
        },
        "head_to_head": head_to_head,
        "match_date": match_date
    }
    
    return match_data

def process_recent_form(matches, team_id, limit=5):
    """Traite les 5 derniers matchs pour obtenir la forme récente"""
    recent_matches = matches[:limit] if len(matches) >= limit else matches
    
    wins = 0
    draws = 0
    losses = 0
    goals_scored = 0
    goals_conceded = 0
    
    for match in recent_matches:
        is_home = match["homeTeam"]["id"] == team_id
        
        if is_home:
            team_goals = match["score"]["fullTime"]["home"] or 0
            opponent_goals = match["score"]["fullTime"]["away"] or 0
        else:
            team_goals = match["score"]["fullTime"]["away"] or 0
            opponent_goals = match["score"]["fullTime"]["home"] or 0
        
        goals_scored += team_goals
        goals_conceded += opponent_goals
        
        if team_goals > opponent_goals:
            wins += 1
        elif team_goals < opponent_goals:
            losses += 1
        else:
            draws += 1
    
    return {
        "matches_played": len(recent_matches),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_scored": goals_scored,
        "goals_conceded": goals_conceded,
        "form_string": "".join(["W" if m["score"]["winner"] == ("HOME_TEAM" if m["homeTeam"]["id"] == team_id else "AWAY_TEAM") 
                                else "D" if m["score"]["winner"] == "DRAW" 
                                else "L" for m in recent_matches])
    }

def find_head_to_head(matches, opponent_id):
    """Trouve les confrontations directes entre les deux équipes"""
    h2h_matches = [m for m in matches if m["homeTeam"]["id"] == opponent_id or m["awayTeam"]["id"] == opponent_id]
    
    return {
        "total_matches": len(h2h_matches),
        "last_matches": h2h_matches[:3] if len(h2h_matches) >= 3 else h2h_matches
    }

def predict_match_result(home_team_id, away_team_id, match_date):
    """Utilise Ollama pour prédire le résultat d'un match"""
    # Préparer les données de match
    match_data = prepare_match_data(home_team_id, away_team_id, match_date)
    
    # Construire le prompt pour Ollama
    prompt = f"""
    Analyse les données suivantes et prédis le résultat du match de football entre {match_data['home_team']['name']} et {match_data['away_team']['name']} le {match_data['match_date']}.
    
    Équipe à domicile ({match_data['home_team']['name']}):
    - Forme récente: {match_data['home_team']['recent_form']['form_string']}
    - Buts marqués dans les derniers matchs: {match_data['home_team']['recent_form']['goals_scored']}
    - Buts encaissés dans les derniers matchs: {match_data['home_team']['recent_form']['goals_conceded']}
    
    Équipe à l'extérieur ({match_data['away_team']['name']}):
    - Forme récente: {match_data['away_team']['recent_form']['form_string']}
    - Buts marqués dans les derniers matchs: {match_data['away_team']['recent_form']['goals_scored']}
    - Buts encaissés dans les derniers matchs: {match_data['away_team']['recent_form']['goals_conceded']}
    
    Confrontations directes:
    - Nombre total de rencontres: {match_data['head_to_head']['total_matches']}
    
    Donne une prédiction détaillée avec un score probable et une explication du raisonnement.
    """
    
    # Appeler l'API Ollama
    ollama_url = current_app.config['OLLAMA_API_URL']
    
    try:
        response = requests.post(
            f"{ollama_url}/generate",
            json={
                "model": "mistral:latest",  # ou un autre modèle disponible sur votre instance Ollama
                "prompt": prompt,
                "stream": False
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            prediction = result.get("response", "")
            
            # Analyser la prédiction pour extraire le score
            # Ceci est une version simplifiée, vous pourriez vouloir utiliser une regex ou une analyse NLP
            score_prediction = extract_score_from_prediction(prediction)
            
            return {
                "home_team": match_data['home_team']['name'],
                "away_team": match_data['away_team']['name'],
                "predicted_winner": determine_winner(score_prediction),
                "predicted_score": score_prediction,
                "explanation": prediction,
                "confidence": calculate_confidence(prediction)
            }
        else:
            return {
                "error": f"Erreur lors de l'appel à Ollama: {response.status_code}",
                "home_team": match_data['home_team']['name'],
                "away_team": match_data['away_team']['name']
            }
    except Exception as e:
        return {
            "error": f"Exception lors de l'appel à Ollama: {str(e)}",
            "home_team": match_data['home_team']['name'],
            "away_team": match_data['away_team']['name']
        }

def extract_score_from_prediction(prediction_text):
    """Extrait le score prédit du texte de prédiction"""
    # Cette fonction pourrait être améliorée avec du NLP ou des regex plus avancés
    import re
    
    # Recherche des motifs comme "2-1", "3:2", etc.
    score_patterns = re.findall(r'(\d+)[-:](\d+)', prediction_text)
    
    if score_patterns:
        # Prendre le premier score trouvé
        home_score, away_score = score_patterns[0]
        return f"{home_score}-{away_score}"
    else:
        return "Indéterminé"

def determine_winner(score_prediction):
    """Détermine l'équipe gagnante en fonction du score prédit"""
    if score_prediction == "Indéterminé":
        return "Indéterminé"
    
    try:
        home_score, away_score = score_prediction.split("-")
        home_score = int(home_score)
        away_score = int(away_score)
        
        if home_score > away_score:
            return "home"
        elif away_score > home_score:
            return "away"
        else:
            return "draw"
    except:
        return "Indéterminé"

def calculate_confidence(prediction_text):
    """Calcule un niveau de confiance approximatif basé sur le texte de prédiction"""
    # Cette fonction est très simplifiée et pourrait être améliorée
    confidence_words = {
        "élevée": ["certainement", "assurément", "très probable", "forte probabilité"],
        "moyenne": ["probable", "possiblement", "pourrait", "chance"],
        "faible": ["incertain", "difficile à dire", "imprévisible", "hasardeux"]
    }
    
    prediction_lower = prediction_text.lower()
    
    for level, words in confidence_words.items():
        for word in words:
            if word in prediction_lower:
                return level
    
    return "moyenne"  # Par défaut