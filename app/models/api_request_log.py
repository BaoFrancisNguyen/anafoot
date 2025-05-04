# app/models/api_request_log.py
from app import db
from datetime import datetime

class APIRequestLog(db.Model):
    """
    Modèle pour le suivi des requêtes API
    """
    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.String(100), nullable=False)  # Endpoint API appelé
    status_code = db.Column(db.Integer)  # Code de statut HTTP
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)  # Date/heure de la requête
    
    def __repr__(self):
        return f'<APIRequestLog {self.id} {self.endpoint} {self.status_code}>'