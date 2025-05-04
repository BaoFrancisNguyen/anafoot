# app/models/player.py
from app import db
from datetime import datetime

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    api_id = db.Column(db.Integer, unique=True)  # ID de l'API externe
    name = db.Column(db.String(120), nullable=False)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    date_of_birth = db.Column(db.Date)
    nationality = db.Column(db.String(50))
    position = db.Column(db.String(20))
    shirt_number = db.Column(db.Integer)
    photo_url = db.Column(db.String(255))
    
    # Clé étrangère vers le club
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Player {self.name}>'
    
def get_current_season_stats(self):
    """
    Récupère les statistiques du joueur pour la saison actuelle ou récente
    Cherche dans plusieurs formats de saison pour maximiser les chances de trouver des données
    """
    from app.models.player_stats import PlayerStats
    import logging
    
    # Liste des saisons possibles, de la plus récente à la plus ancienne
    # Inclut différents formats de saison pour maximiser les chances de correspondance
    possible_seasons = [
        "2024/2025", "2024-2025", "2024", 
        "2023/2024", "2023-2024", "2023",
        "2022/2023", "2022-2023", "2022"
    ]
    
    # Recherche dans chaque format de saison jusqu'à trouver des statistiques
    stats = None
    matched_season = None
    
    for season in possible_seasons:
        try:
            # Essayer de trouver des statistiques pour cette saison
            stats_record = PlayerStats.query.filter_by(player_id=self.id, season=season).first()
            if stats_record:
                stats = stats_record
                matched_season = season
                # Sortir de la boucle dès qu'on trouve des statistiques
                break
        except Exception as e:
            logging.warning(f"Erreur lors de la recherche de statistiques pour la saison {season}: {str(e)}")
            continue
    
    # Si aucune statistique n'est trouvée, créer un dictionnaire avec des valeurs par défaut
    if not stats:
        logging.info(f"Aucune statistique trouvée pour le joueur {self.id} ({self.name})")
        
        # Base de statistiques pour tous les joueurs
        default_stats = {
            "matches_played": 0,
            "minutes_played": 0,
            "goals": 0,
            "assists": 0,
            "yellow_cards": 0,
            "red_cards": 0,
            "rating": 0,
            "motm": 0,
            "shots": 0,
            "shots_on_target": 0,
            "passes": 0,
            "passes_completed": 0,
            "key_passes": 0,
            "tackles": 0,
            "interceptions": 0,
            "clearances": 0,
            "duels": 0,
            "duels_won": 0,
            "fouls": 0,
            "fouls_drawn": 0,
            "season": "2024/2025"  # Saison par défaut
        }
        
        # Ajouter des statistiques spécifiques selon le poste
        if self.position and "ttaquant" in self.position:  # Couvre "Attaquant" et variations
            default_stats.update({
                "big_chances_missed": 0,
                "hit_woodwork": 0,
                "conversion_rate": 0.0
            })
        elif self.position and "ilieu" in self.position:  # Couvre "Milieu" et variations
            default_stats.update({
                "through_balls": 0,
                "crosses": 0,
                "crosses_completed": 0,
                "long_balls": 0,
                "pass_accuracy": 0.0
            })
        elif self.position and "éfenseur" in self.position:  # Couvre "Défenseur" et variations
            default_stats.update({
                "blocks": 0,
                "errors_leading_to_goal": 0,
                "own_goals": 0,
                "clean_sheets": 0
            })
        elif self.position and "ardien" in self.position:  # Couvre "Gardien" et variations
            default_stats.update({
                "saves": 0,
                "clean_sheets": 0,
                "penalties_saved": 0,
                "goals_conceded": 0,
                "save_percentage": 0.0
            })
            
        return default_stats
    
    # Si des statistiques ont été trouvées mais sont stockées comme un objet
    # Convertir en dictionnaire
    if not isinstance(stats, dict):
        try:
            # Si stats a une méthode to_dict, l'utiliser
            if hasattr(stats, 'to_dict') and callable(getattr(stats, 'to_dict')):
                return stats.to_dict()
            
            # Sinon, créer manuellement un dictionnaire à partir des attributs
            stats_dict = {}
            for attr in dir(stats):
                # Exclure les attributs privés et les méthodes
                if not attr.startswith('_') and not callable(getattr(stats, attr)):
                    stats_dict[attr] = getattr(stats, attr)
            
            logging.info(f"Statistiques trouvées pour le joueur {self.id} ({self.name}) de la saison {matched_season}")
            return stats_dict
        except Exception as e:
            logging.error(f"Erreur lors de la conversion des statistiques en dictionnaire: {str(e)}")
            # En cas d'erreur, retourner l'objet original
            return stats
    
    # Si stats est déjà un dictionnaire, le retourner directement
    logging.info(f"Statistiques trouvées pour le joueur {self.id} ({self.name}) de la saison {matched_season}")
    return stats