# app/routes/club_routes.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from app.models.club import Club
from app.models.match import Match
from app.services.data_fetcher import get_club_stats, get_club_matches
from app.services.data_processor import process_club_performance
from app import db
import logging

logger = logging.getLogger(__name__)

# Création du Blueprint
club_bp = Blueprint('club', __name__)

@club_bp.route('/')
def index():
    """Liste des clubs"""
    clubs = Club.query.all()
    return render_template('club/index.html', clubs=clubs)

@club_bp.route('/search')
def search():
    """Recherche de clubs"""
    query = request.args.get('q', '')
    if query:
        clubs = Club.query.filter(Club.name.ilike(f'%{query}%')).all()
    else:
        clubs = []
    return render_template('club/search.html', clubs=clubs, query=query)

@club_bp.route('/<int:club_id>')
def club_stats(club_id):
    """Affiche les statistiques d'un club"""
    club_info = get_club_stats(club_id)
    
    if not club_info:
        flash('Club non trouvé', 'danger')
        return redirect(url_for('club.index'))
    
    return render_template('club/stats.html', club=club_info)

@club_bp.route('/<int:club_id>/performance')
def club_performance(club_id):
    """Renvoie les données de performance d'un club au format JSON pour les graphiques"""
    matches = get_club_matches(club_id)
    performance_data = process_club_performance(matches)
    return jsonify(performance_data)

@club_bp.route('/<int:club_id>/matches')
def club_matches(club_id):
    """Affiche les matchs d'un club"""
    club = Club.query.get_or_404(club_id)
    season = request.args.get('season')
    
    matches = get_club_matches(club_id, season)
    
    return render_template('club/matches.html', club=club, matches=matches, season=season)

@club_bp.route('/<int:club_id>/players')
def club_players(club_id):
    """Affiche les joueurs d'un club"""
    club = Club.query.get_or_404(club_id)
    return render_template('club/players.html', club=club)