# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'clé-secrète-par-défaut'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///football_analytics.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL') or 'http://localhost:11434/api'
    FOOTBALL_API_KEY = os.environ.get('FOOTBALL_API_KEY') or 'your-api-key'
    
    # Paramètres pour API-Football
    API_FOOTBALL_KEY = 'b52dad2462e765d262f804b8f70a3e57'  # Votre clé API directement ici
    API_FOOTBALL_HOST = 'api-football-v1.p.rapidapi.com'
    API_FOOTBALL_DAILY_LIMIT = 100
    
    # Paramètres pour la planification des tâches
    SCHEDULER_JOBSTORES = {
        'default': {
            'type': 'sqlalchemy',
            'url': os.environ.get('DATABASE_URL') or 'sqlite:///football_analytics.db'
        }
    }
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = 'Europe/Paris'