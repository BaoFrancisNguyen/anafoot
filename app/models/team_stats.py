# app/models/team_stats.py
from app import db
from datetime import datetime

class TeamStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'))
    season = db.Column(db.String(10))
    
    # Statistiques générales
    matches_played = db.Column(db.Integer, default=0)
    wins = db.Column(db.Integer, default=0)
    draws = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    goals_for = db.Column(db.Integer, default=0)
    goals_against = db.Column(db.Integer, default=0)
    clean_sheets = db.Column(db.Integer, default=0)
    
    # Statistiques offensives
    shots = db.Column(db.Integer, default=0)
    shots_on_target = db.Column(db.Integer, default=0)
    
    # Statistiques de passes
    passes = db.Column(db.Integer, default=0)
    pass_accuracy = db.Column(db.Float, default=0)
    
    # Statistiques défensives
    tackles = db.Column(db.Integer, default=0)
    blocks = db.Column(db.Integer, default=0)
    interceptions = db.Column(db.Integer, default=0)
    
    # Statistiques de discipline
    yellow_cards = db.Column(db.Integer, default=0)
    red_cards = db.Column(db.Integer, default=0)
    fouls = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<TeamStats club_id={self.club_id} season={self.season}>'