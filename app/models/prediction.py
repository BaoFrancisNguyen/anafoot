# app/models/prediction.py
from app import db
from datetime import datetime

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    match = db.relationship('Match')
    
    # Prédiction
    predicted_home_score = db.Column(db.Integer)
    predicted_away_score = db.Column(db.Integer)
    predicted_winner = db.Column(db.String(10))  # 'home', 'away', 'draw'
    confidence = db.Column(db.String(10))  # 'élevée', 'moyenne', 'faible'
    
    # Explicabilité
    explanation = db.Column(db.Text)
    key_factors = db.Column(db.Text)  # Stocké en JSON
    
    # Exactitude (à remplir après le match)
    was_correct = db.Column(db.Boolean, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Prediction {self.match.home_team.name} vs {self.match.away_team.name} - {self.predicted_home_score}:{self.predicted_away_score}>'
    
    def get_key_factors(self):
        """Convertit les facteurs clés JSON en liste Python"""
        import json
        if self.key_factors:
            return json.loads(self.key_factors)
        return []
    
    def set_key_factors(self, factors):
        """Convertit la liste des facteurs clés en JSON pour le stockage"""
        import json
        self.key_factors = json.dumps(factors)