# app/models/club.py
from app import db
from datetime import datetime

class Club(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    api_id = db.Column(db.Integer, unique=True)  # ID de l'API externe
    name = db.Column(db.String(120), nullable=False)
    short_name = db.Column(db.String(10))
    tla = db.Column(db.String(3))  # Code à trois lettres (ex: ARS pour Arsenal)
    crest = db.Column(db.String(255))  # URL du logo
    address = db.Column(db.String(255))
    phone = db.Column(db.String(20))
    website = db.Column(db.String(255))
    email = db.Column(db.String(100))
    founded = db.Column(db.Integer)
    club_colors = db.Column(db.String(100))
    venue = db.Column(db.String(120))
    
    # Relations
    players = db.relationship('Player', backref='club', lazy=True)
    home_matches = db.relationship('Match', foreign_keys='Match.home_team_id', backref='home_team', lazy=True)
    away_matches = db.relationship('Match', foreign_keys='Match.away_team_id', backref='away_team', lazy=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Club {self.name}>'
    
    def get_all_matches(self):
        """Récupère tous les matchs d'un club (domicile et extérieur)"""
        from app.models.match import Match
        return Match.query.filter(
            (Match.home_team_id == self.id) | (Match.away_team_id == self.id)
        ).order_by(Match.date.desc()).all()
    
    def get_recent_form(self, limit=5):
        """Récupère les X derniers matchs d'un club avec leurs résultats"""
        matches = self.get_all_matches()[:limit]
        form = []
        
        for match in matches:
            # Déterminer si le club est l'équipe à domicile ou à l'extérieur
            is_home = (match.home_team_id == self.id)
            
            if match.status != 'FINISHED':
                continue
                
            # Calculer les buts marqués et encaissés
            if is_home:
                team_goals = match.home_team_score
                opponent_goals = match.away_team_score
                opponent = match.away_team.name
            else:
                team_goals = match.away_team_score
                opponent_goals = match.home_team_score
                opponent = match.home_team.name
            
            # Déterminer le résultat
            if team_goals > opponent_goals:
                result = "W"
            elif team_goals < opponent_goals:
                result = "L"
            else:
                result = "D"
            
            form.append({
                "date": match.date,
                "opponent": opponent,
                "result": result,
                "score": f"{team_goals}-{opponent_goals}",
                "is_home": is_home
            })
        
        return form
    
    def get_upcoming_matches(self, limit=5):
        """Récupère les prochains matchs programmés pour ce club"""
        from app.models.match import Match
        now = datetime.utcnow()
        
        upcoming = Match.query.filter(
            ((Match.home_team_id == self.id) | (Match.away_team_id == self.id)) &
            (Match.date > now)
        ).order_by(Match.date.asc()).limit(limit).all()
        
        matches = []
        for match in upcoming:
            is_home = (match.home_team_id == self.id)
            
            if is_home:
                opponent = match.away_team.name
                opponent_logo = match.away_team.crest
            else:
                opponent = match.home_team.name
                opponent_logo = match.home_team.crest
            
            matches.append({
                "date": match.date,
                "competition": match.competition,
                "opponent": opponent,
                "opponent_logo": opponent_logo,
                "is_home": is_home
            })
        
        return matches
    
    def get_player_stats(self):
        """Récupère les statistiques cumulées des joueurs de ce club"""
        stats = {
            "total_goals": 0,
            "total_assists": 0,
            "total_clean_sheets": 0,
            "top_scorers": [],
            "top_assisters": []
        }
        
        # On pourrait implémenter ici une logique pour calculer ces statistiques
        # à partir des données des joueurs et des matchs
        
        return stats