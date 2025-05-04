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
        """Récupère les statistiques du joueur pour la saison en cours"""
        from app.models.player_stats import PlayerStats
        # On suppose que la saison en cours est 2024/2025
        current_season = "2024/2025"
        
        stats = PlayerStats.query.filter_by(
            player_id=self.id,
            season=current_season
        ).first()
        
        if not stats:
            stats = {
                "matches_played": 0,
                "minutes_played": 0,
                "goals": 0,
                "assists": 0,
                "yellow_cards": 0,
                "red_cards": 0
            }
            
            # Ajouter des statistiques spécifiques selon le poste
            if self.position == "Attaquant":
                stats.update({
                    "shots": 0,
                    "shots_on_target": 0,
                    "conversion_rate": 0
                })
            elif self.position == "Milieu":
                stats.update({
                    "passes": 0,
                    "pass_accuracy": 0,
                    "key_passes": 0
                })
            elif self.position == "Défenseur":
                stats.update({
                    "tackles": 0,
                    "interceptions": 0,
                    "clearances": 0
                })
            elif self.position == "Gardien":
                stats.update({
                    "saves": 0,
                    "clean_sheets": 0,
                    "save_percentage": 0
                })
        
        return stats