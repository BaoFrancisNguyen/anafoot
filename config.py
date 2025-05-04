# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'clé-secrète-par-défaut'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///football_analytics.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL') or 'http://localhost:11434/api'
    FOOTBALL_API_KEY = os.environ.get('FOOTBALL_API_KEY') or 'your-api-key'