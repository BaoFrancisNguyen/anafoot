# app/models/api_quota.py
from app import db
from datetime import datetime, date

class APIQuota(db.Model):
    """
    Modèle pour le suivi des quotas d'API
    """
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=date.today)  # Date du quota
    used = db.Column(db.Integer, default=0)  # Nombre de requêtes utilisées
    limit = db.Column(db.Integer, default=100)  # Limite quotidienne
    
    def __repr__(self):
        return f'<APIQuota {self.date} {self.used}/{self.limit}>'