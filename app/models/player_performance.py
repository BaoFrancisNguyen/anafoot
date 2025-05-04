# app/models/player_performance.py
from app import db
from datetime import datetime

class PlayerPerformance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    team_id = db.Column(db.Integer, db.ForeignKey('club.id'))
    
    # Relations
    match = db.relationship('Match')
    player = db.relationship('Player')
    team = db.relationship('Club')
    
    # Informations de base
    position = db.Column(db.String(20))
    shirt_number = db.Column(db.Integer)
    captain = db.Column(db.Boolean, default=False)
    
    # Temps de jeu
    minutes_played = db.Column(db.Integer)
    
    # Statistiques générales
    goals = db.Column(db.Integer, default=0)
    assists = db.Column(db.Integer, default=0)
    yellow_cards = db.Column(db.Integer, default=0)
    red_card = db.Column(db.Boolean, default=False)
    
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
    goals_conceded = db.Column(db.Integer, default=0)
    penalties_saved = db.Column(db.Integer, default=0)
    
    # Position moyenne sur le terrain et carte de chaleur
    heatmap_data = db.Column(db.Text, nullable=True)  # Stocké en JSON
    avg_position_x = db.Column(db.Float, nullable=True)
    avg_position_y = db.Column(db.Float, nullable=True)
    
    # Note de performance (sur 10)
    rating = db.Column(db.Float, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<PlayerPerformance {self.player.name} - {self.match.home_team.name} vs {self.match.away_team.name}>'