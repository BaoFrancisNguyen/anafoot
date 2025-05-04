# app/models/match_event.py
from app import db
from datetime import datetime

class MatchEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    minute = db.Column(db.Integer)
    extra_minute = db.Column(db.Integer, nullable=True)  # Pour le temps additionnel
    type = db.Column(db.String(20))  # GOAL, CARD, SUBSTITUTION, etc.
    
    # Joueur concerné
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    player = db.relationship('Player', foreign_keys=[player_id])
    
    # Pour les substitutions
    secondary_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    secondary_player = db.relationship('Player', foreign_keys=[secondary_player_id])
    
    # Pour les cartons
    card_type = db.Column(db.String(10), nullable=True)  # YELLOW, RED, YELLOW_RED
    
    # Pour les buts
    goal_type = db.Column(db.String(20), nullable=True)  # NORMAL, OWN_GOAL, PENALTY
    assist_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)
    assist_player = db.relationship('Player', foreign_keys=[assist_player_id])
    
    # Équipe
    team_id = db.Column(db.Integer, db.ForeignKey('club.id'))
    team = db.relationship('Club')
    
    # Description
    detail = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<MatchEvent {self.type} - {self.player.name} - {self.minute}\'>'