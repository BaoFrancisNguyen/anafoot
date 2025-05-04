# app/models/player_position_heatmap.py
from app import db
from datetime import datetime
import json

class PlayerPositionHeatmap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'))
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'))
    
    # Relations
    player = db.relationship('Player')
    match = db.relationship('Match')
    
    # Données de la carte de chaleur
    heatmap_data = db.Column(db.Text, nullable=False)  # Stocké en JSON
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<PlayerPositionHeatmap player_id={self.player_id} match_id={self.match_id}>'
    
    def get_heatmap_data(self):
        """Convertit les données JSON en objet Python"""
        if self.heatmap_data:
            return json.loads(self.heatmap_data)
        return []
    
    def set_heatmap_data(self, data):
        """Convertit les données Python en JSON pour le stockage"""
        self.heatmap_data = json.dumps(data)