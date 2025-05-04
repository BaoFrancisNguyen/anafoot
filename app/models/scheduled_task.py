# app/models/scheduled_task.py
from app import db
from datetime import datetime
import json

class ScheduledTask(db.Model):
    """
    Modèle pour les tâches API planifiées
    """
    id = db.Column(db.Integer, primary_key=True)
    task_type = db.Column(db.String(50), nullable=False)  # import_teams, import_players, etc.
    endpoint = db.Column(db.String(100), nullable=False)  # Endpoint API à appeler
    parameters = db.Column(db.Text)  # Paramètres de la requête en JSON
    
    # Planification
    execution_time = db.Column(db.DateTime)  # Date/heure d'exécution
    recurrence = db.Column(db.String(50))  # Expression cron pour les tâches récurrentes
    
    # Métadonnées
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run = db.Column(db.DateTime)
    
    # Statut et résultat
    status = db.Column(db.String(20))  # PENDING, SCHEDULED, RUNNING, COMPLETED, ERROR
    result = db.Column(db.Text)  # Résultat de l'exécution en JSON
    
    def __repr__(self):
        return f'<ScheduledTask {self.id} {self.task_type} {self.status}>'
    
    def get_parameters(self):
        """Convertit les paramètres JSON en dictionnaire"""
        if self.parameters:
            return json.loads(self.parameters)
        return {}
    
    def set_parameters(self, params):
        """Convertit le dictionnaire de paramètres en JSON"""
        self.parameters = json.dumps(params)
    
    def get_result(self):
        """Convertit le résultat JSON en dictionnaire"""
        if self.result:
            return json.loads(self.result)
        return {}
    
    def set_result(self, result):
        """Convertit le dictionnaire de résultat en JSON"""
        self.result = json.dumps(result)