# app/__init__.py
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config
import logging
import os

# Initialisation des extensions
db = SQLAlchemy()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Initialisation des extensions avec l'application
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Configuration du logging
    if not app.debug and not app.testing:
        if not os.path.exists('logs'):
            os.mkdir('logs')
        file_handler = logging.FileHandler('logs/football_analytics.log')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        
        app.logger.setLevel(logging.INFO)
        app.logger.info('Application de football analytics démarrée')
    
    # Enregistrement des blueprints
    from app.routes.club_routes import club_bp
    from app.routes.player_routes import player_bp
    from app.routes.prediction_routes import prediction_bp
    from app.routes.whoscored_routes import whoscored_bp
    
    app.register_blueprint(club_bp, url_prefix='/club')
    app.register_blueprint(player_bp, url_prefix='/player')
    app.register_blueprint(prediction_bp, url_prefix='/predict')
    app.register_blueprint(whoscored_bp, url_prefix='/whoscored')
    
    # Route principale
    @app.route('/')
    def index():
        return render_template('index.html')
    
    return app

# Import des modèles pour que Flask-Migrate les détecte
from app.models import club, player, match, player_stats, match_event, player_performance, player_position_heatmap, prediction