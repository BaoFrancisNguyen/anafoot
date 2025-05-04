# app/models/match.py
from app import db
from datetime import datetime

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    api_id = db.Column(db.Integer, unique=True)  # ID de l'API externe
    competition = db.Column(db.String(100))
    season = db.Column(db.String(10))
    matchday = db.Column(db.Integer)
    date = db.Column(db.DateTime)
    status = db.Column(db.String(20))  # SCHEDULED, LIVE, IN_PLAY, PAUSED, FINISHED, etc.
    
    # Équipes
    home_team_id = db.Column(db.Integer, db.ForeignKey('club.id'))
    away_team_id = db.Column(db.Integer, db.ForeignKey('club.id'))
    
    # Scores
    home_team_score = db.Column(db.Integer, default=0)
    away_team_score = db.Column(db.Integer, default=0)
    
    # Détails
    half_time_home = db.Column(db.Integer)
    half_time_away = db.Column(db.Integer)
    extra_time_home = db.Column(db.Integer)
    extra_time_away = db.Column(db.Integer)
    penalties_home = db.Column(db.Integer)
    penalties_away = db.Column(db.Integer)
    
    # Autres statistiques
    home_possession = db.Column(db.Float)
    away_possession = db.Column(db.Float)
    home_shots = db.Column(db.Integer)
    away_shots = db.Column(db.Integer)
    home_shots_on_target = db.Column(db.Integer)
    away_shots_on_target = db.Column(db.Integer)
    home_corners = db.Column(db.Integer)
    away_corners = db.Column(db.Integer)
    home_fouls = db.Column(db.Integer)
    away_fouls = db.Column(db.Integer)
    home_yellow_cards = db.Column(db.Integer)
    away_yellow_cards = db.Column(db.Integer)
    home_red_cards = db.Column(db.Integer)
    away_red_cards = db.Column(db.Integer)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Match {self.home_team.name} vs {self.away_team.name} - {self.date}>'
    
    def get_match_events(self):
        """Récupère tous les événements d'un match (buts, cartons, etc.)"""
        from app.models.match_event import MatchEvent
        return MatchEvent.query.filter_by(match_id=self.id).order_by(MatchEvent.minute).all()
    
    def get_player_performances(self):
        """Récupère les performances des joueurs dans ce match"""
        from app.models.player_performance import PlayerPerformance
        return PlayerPerformance.query.filter_by(match_id=self.id).all()