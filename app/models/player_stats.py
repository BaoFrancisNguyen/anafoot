# app/models/player_stats.py
from app import db
from datetime import datetime

class PlayerStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    season = db.Column(db.String(10))
    
    # Statistiques générales
    matches_played = db.Column(db.Integer, default=0)
    minutes_played = db.Column(db.Integer, default=0)
    goals = db.Column(db.Integer, default=0)
    assists = db.Column(db.Integer, default=0)
    yellow_cards = db.Column(db.Integer, default=0)
    red_cards = db.Column(db.Integer, default=0)
    
    # Statistiques d'attaquant
    shots = db.Column(db.Integer, default=0)
    shots_on_target = db.Column(db.Integer, default=0)
    hit_woodwork = db.Column(db.Integer, default=0)
    big_chances_missed = db.Column(db.Integer, default=0)
    
    # Statistiques de milieu
    passes = db.Column(db.Integer, default=0)
    passes_completed = db.Column(db.Integer, default=0)
    key_passes = db.Column(db.Integer, default=0)
    crosses = db.Column(db.Integer, default=0)
    crosses_completed = db.Column(db.Integer, default=0)
    through_balls = db.Column(db.Integer, default=0)
    
    # Statistiques de défenseur
    tackles = db.Column(db.Integer, default=0)
    tackles_won = db.Column(db.Integer, default=0)
    interceptions = db.Column(db.Integer, default=0)
    clearances = db.Column(db.Integer, default=0)
    blocks = db.Column(db.Integer, default=0)
    duels = db.Column(db.Integer, default=0)
    duels_won = db.Column(db.Integer, default=0)
    
    # Statistiques de gardien
    saves = db.Column(db.Integer, default=0)
    clean_sheets = db.Column(db.Integer, default=0)
    goals_conceded = db.Column(db.Integer, default=0)
    penalties_saved = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<PlayerStats player_id={self.player_id} season={self.season}>'
    
    def calculate_derived_stats(self):
        """Calculer des statistiques dérivées comme le taux de conversion"""
        stats = {}
        
        if self.shots > 0:
            stats['conversion_rate'] = round((self.goals / self.shots) * 100, 2)
        else:
            stats['conversion_rate'] = 0
        
        if self.passes > 0:
            stats['pass_accuracy'] = round((self.passes_completed / self.passes) * 100, 2)
        else:
            stats['pass_accuracy'] = 0
        
        if self.duels > 0:
            stats['duel_win_rate'] = round((self.duels_won / self.duels) * 100, 2)
        else:
            stats['duel_win_rate'] = 0
        
        if self.tackles > 0:
            stats['tackle_success_rate'] = round((self.tackles_won / self.tackles) * 100, 2)
        else:
            stats['tackle_success_rate'] = 0
        
        if self.shots_on_target > 0:
            stats['shots_on_target_ratio'] = round((self.shots_on_target / self.shots) * 100, 2)
        else:
            stats['shots_on_target_ratio'] = 0
        
        return stats