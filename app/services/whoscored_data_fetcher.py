# app/services/whoscored_data_fetcher.py
import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import time
import random
import logging
from app.models.player import Player
from app.models.club import Club
from app.models.match import Match
from app.models.player_stats import PlayerStats
from app import db
from datetime import datetime

logger = logging.getLogger(__name__)

class WhoScoredDataFetcher:
    """
    Service pour récupérer les données depuis fr.whoscored.com
    """
    
    BASE_URL = "https://fr.whoscored.com"
    
    # Liste des User-Agents pour la rotation
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.3 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:98.0) Gecko/20100101 Firefox/98.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36'
    ]
    
    # Mapping des identifiants de ligues WhoScored vers nos identifiants
    LEAGUE_MAPPING = {
        '252/2': 'premier_league',    # Premier League
        '206/4': 'la_liga',           # La Liga
        '108/5': 'serie_a',           # Serie A
        '81/3': 'bundesliga',         # Bundesliga
        '74/22': 'ligue_1'            # Ligue 1
    }
    
    def __init__(self, proxy=None):
        self.session = requests.Session()
        self.update_headers()
        self.proxy = proxy
    
    def update_headers(self):
        """
        Met à jour les headers HTTP avec un User-Agent aléatoire
        """
        user_agent = random.choice(self.USER_AGENTS)
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://fr.whoscored.com/',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
            'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'DNT': '1'
        }
        self.session.headers.update(headers)
        
    def _get_page(self, url, retries=5, delay=5):
        """
        Récupère une page avec gestion d'erreurs et délai entre les tentatives
        """
        proxies = None
        if self.proxy:
            proxies = {'http': self.proxy, 'https': self.proxy}
        
        # Mettre à jour les headers avec un User-Agent aléatoire
        self.update_headers()
        
        # Ajouter un délai aléatoire avant chaque requête
        time.sleep(random.uniform(2, 5))
        
        for attempt in range(retries):
            try:
                # Ajouter un cookie aléatoire pour éviter la détection
                cookies = {
                    'visitor_id': f"{random.randint(10000000, 99999999)}",
                    'session_id': f"{random.randint(10000000, 99999999)}"
                }
                
                response = self.session.get(url, proxies=proxies, timeout=15, cookies=cookies)
                response.raise_for_status()
                
                # Sauvegarder les cookies pour les requêtes futures
                self.session.cookies.update(response.cookies)
                
                # Ajouter un délai plus long entre les tentatives
                time.sleep(random.uniform(delay, delay * 2))
                
                return response.text
            except requests.RequestException as e:
                logger.warning(f"Tentative {attempt+1}/{retries} échouée pour {url}: {str(e)}")
                if attempt < retries - 1:
                    # Délai exponentiel entre les tentatives
                    wait_time = delay * (2 ** attempt)
                    logger.info(f"Attente de {wait_time} secondes avant la prochaine tentative")
                    time.sleep(wait_time)
                    # Changer l'User-Agent pour la prochaine tentative
                    self.update_headers()
                else:
                    logger.error(f"Échec après {retries} tentatives pour {url}")
                    raise
    
    def get_league_teams(self, league_id, season_id):
        """
        Récupère la liste des équipes pour une ligue et une saison données
        
        Args:
            league_id: l'identifiant de la ligue (ex: '252/2' pour Premier League)
            season_id: l'identifiant de la saison (ex: '9618')
        
        Returns:
            Une liste de dictionnaires contenant les informations des équipes
        """
        url = f"{self.BASE_URL}/Regions/{league_id}/Tournaments/Seasons/{season_id}/Stages/"
        
        html = self._get_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        teams = []
        team_links = soup.select('table.standings a[href*="/Teams/"]')
        
        if not team_links:
            # Essayer un sélecteur alternatif
            team_links = soup.select('div.tournament-teamlist a[href*="/Teams/"]')
        
        if not team_links:
            logger.warning(f"Aucune équipe trouvée pour la ligue {league_id}, saison {season_id}")
            # Sauvegarder la page HTML pour débogage
            with open(f"debug_teams_{league_id}_{season_id}.html", "w", encoding="utf-8") as f:
                f.write(html)
        
        for link in team_links:
            href = link['href']
            team_id = href.split('/')[2] if '/Teams/' in href else None
            
            if team_id:
                team_name = link.text.strip()
                teams.append({
                    'id': team_id,
                    'name': team_name,
                    'league_id': league_id,
                    'season_id': season_id
                })
        
        logger.info(f"Nombre d'équipes trouvées: {len(teams)}")
        return teams
    
    def get_team_players(self, team_id, season_id):
        """
        Récupère la liste des joueurs pour une équipe et une saison données
        
        Args:
            team_id: l'identifiant de l'équipe
            season_id: l'identifiant de la saison
        
        Returns:
            Une liste de dictionnaires contenant les informations des joueurs
        """
        url = f"{self.BASE_URL}/Teams/{team_id}/Show/"
        
        # Ajouter un paramètre aléatoire pour éviter la mise en cache
        url = f"{url}?r={random.randint(1000, 9999)}"
        
        html = self._get_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        players = []
        player_rows = soup.select('table#player-table-statistics-body tr')
        
        if not player_rows:
            # Essayer un sélecteur alternatif
            player_rows = soup.select('table.player-statistics tbody tr')
        
        if not player_rows:
            logger.warning(f"Aucun joueur trouvé pour l'équipe {team_id}, saison {season_id}")
            # Sauvegarder la page HTML pour débogage
            with open(f"debug_players_{team_id}_{season_id}.html", "w", encoding="utf-8") as f:
                f.write(html)
        
        for row in player_rows:
            player_link = row.select_one('a[href*="/Players/"]')
            if not player_link:
                continue
                
            player_id = player_link['href'].split('/')[2]
            player_name = player_link.text.strip()
            
            # Récupérer la position du joueur
            position_cell = row.select_one('td:nth-child(2)')
            position = position_cell.text.strip() if position_cell else 'Unknown'
            
            players.append({
                'id': player_id,
                'name': player_name,
                'team_id': team_id,
                'position': position,
                'season_id': season_id
            })
        
        logger.info(f"Nombre de joueurs trouvés: {len(players)}")
        return players
    
    def get_player_stats(self, player_id, season_id):
        """
        Récupère les statistiques détaillées d'un joueur pour une saison donnée
        
        Args:
            player_id: l'identifiant du joueur
            season_id: l'identifiant de la saison
        
        Returns:
            Un dictionnaire contenant les statistiques du joueur
        """
        url = f"{self.BASE_URL}/Players/{player_id}/Show/"
        
        # Ajouter un paramètre aléatoire pour éviter la mise en cache
        url = f"{url}?r={random.randint(1000, 9999)}"
        
        html = self._get_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        stats = {
            'player_id': player_id,
            'season_id': season_id,
            'summary': {},
            'defensive': {},
            'offensive': {},
            'passing': {},
            'detailed': {}
        }
        
        # Statistiques générales (résumé)
        summary_table = soup.select_one('table.player-summary-statistics')
        if summary_table:
            for row in summary_table.select('tr'):
                cells = row.select('td')
                if len(cells) >= 2:
                    key = cells[0].text.strip().lower().replace(' ', '_')
                    value = cells[1].text.strip()
                    stats['summary'][key] = self._convert_value(value)
        else:
            logger.warning(f"Aucune statistique trouvée pour le joueur {player_id}, saison {season_id}")
            # Sauvegarder la page HTML pour débogage
            with open(f"debug_player_stats_{player_id}_{season_id}.html", "w", encoding="utf-8") as f:
                f.write(html)
        
        # Les autres statistiques nécessitent JavaScript, donc elles seront récupérées par le scraper Selenium
        return stats
    
    def get_match_details(self, match_id):
        """
        Récupère les détails d'un match (événements, statistiques, etc.)
        
        Args:
            match_id: l'identifiant du match
        
        Returns:
            Un dictionnaire contenant les détails du match
        """
        url = f"{self.BASE_URL}/Matches/{match_id}/MatchReport/"
        
        # Ajouter un paramètre aléatoire pour éviter la mise en cache
        url = f"{url}?r={random.randint(1000, 9999)}"
        
        html = self._get_page(url)
        soup = BeautifulSoup(html, 'html.parser')
        
        match_details = {
            'id': match_id,
            'events': [],
            'team_stats': {},
            'player_ratings': {}
        }
        
        # Récupérer les événements du match (buts, cartons, etc.)
        event_list = soup.select('div.match-centre-events-wrapper li')
        for event in event_list:
            event_type = None
            if 'goal' in event.get('class', []):
                event_type = 'goal'
            elif 'card' in event.get('class', []):
                event_type = 'card'
            elif 'sub' in event.get('class', []):
                event_type = 'substitution'
            
            if event_type:
                event_minute = event.select_one('span.minute')
                event_minute_text = event_minute.text.strip().replace("'", '') if event_minute else ''
                
                player_name = event.select_one('a')
                player_name_text = player_name.text.strip() if player_name else None
                
                match_details['events'].append({
                    'type': event_type,
                    'minute': event_minute_text,
                    'player': player_name_text
                })
        
        # Récupérer les statistiques des équipes
        stats_table = soup.select_one('div.match-centre-stats')
        if stats_table:
            categories = stats_table.select('div.stat-category')
            for category in categories:
                stat_name_elem = category.select_one('div.stat-name')
                home_stat_elem = category.select_one('div.home-stat')
                away_stat_elem = category.select_one('div.away-stat')
                
                if stat_name_elem and home_stat_elem and away_stat_elem:
                    stat_name = stat_name_elem.text.strip().lower().replace(' ', '_')
                    home_value = home_stat_elem.text.strip()
                    away_value = away_stat_elem.text.strip()
                    
                    match_details['team_stats'][stat_name] = {
                        'home': self._convert_value(home_value),
                        'away': self._convert_value(away_value)
                    }
        
        # Récupérer les notes des joueurs
        ratings_home = soup.select('div.home-team div.player-rating')
        ratings_away = soup.select('div.away-team div.player-rating')
        
        for rating in ratings_home:
            player_elem = rating.select_one('a')
            rating_elem = rating.select_one('span.rating')
            
            if player_elem and rating_elem:
                player_name = player_elem.text.strip()
                player_rating = rating_elem.text.strip()
                try:
                    match_details['player_ratings'][player_name] = float(player_rating)
                except ValueError:
                    match_details['player_ratings'][player_name] = 0.0
        
        for rating in ratings_away:
            player_elem = rating.select_one('a')
            rating_elem = rating.select_one('span.rating')
            
            if player_elem and rating_elem:
                player_name = player_elem.text.strip()
                player_rating = rating_elem.text.strip()
                try:
                    match_details['player_ratings'][player_name] = float(player_rating)
                except ValueError:
                    match_details['player_ratings'][player_name] = 0.0
        
        if not match_details['events'] and not match_details['team_stats'] and not match_details['player_ratings']:
            logger.warning(f"Aucun détail trouvé pour le match {match_id}")
            # Sauvegarder la page HTML pour débogage
            with open(f"debug_match_{match_id}.html", "w", encoding="utf-8") as f:
                f.write(html)
        
        return match_details
    
    def _convert_value(self, value):
        """
        Convertit une valeur en string vers le type approprié (int, float, etc.)
        """
        if not value:
            return 0
            
        value = value.strip()
        
        # Essayer de convertir en entier
        try:
            return int(value)
        except ValueError:
            pass
        
        # Essayer de convertir en nombre à virgule
        try:
            # Remplacer la virgule par un point pour les nombres décimaux
            if ',' in value:
                value = value.replace(',', '.')
            return float(value)
        except ValueError:
            pass
        
        # Pour les pourcentages
        if '%' in value:
            try:
                return float(value.replace('%', '')) / 100
            except ValueError:
                pass
        
        # Retourner la valeur comme une chaîne si les conversions échouent
        return value
    
    def import_league_data(self, league_id, season_id):
        """
        Importe toutes les données d'une ligue pour une saison (équipes, joueurs, statistiques)
        
        Args:
            league_id: l'identifiant de la ligue
            season_id: l'identifiant de la saison
        """
        logger.info(f"Importation des données pour la ligue {league_id}, saison {season_id}")
        
        # Récupérer la liste des équipes
        teams = self.get_league_teams(league_id, season_id)
        
        for team in teams:
            # Ajouter un délai entre chaque traitement d'équipe
            time.sleep(random.uniform(5, 10))
            
            # Vérifier si l'équipe existe déjà en base de données
            db_team = Club.query.filter_by(api_id=team['id']).first()
            
            if not db_team:
                # Créer une nouvelle équipe
                db_team = Club(
                    api_id=team['id'],
                    name=team['name'],
                    # Autres champs...
                )
                db.session.add(db_team)
                db.session.commit()
                logger.info(f"Équipe créée: {team['name']}")
            
            # Récupérer la liste des joueurs de l'équipe
            players = self.get_team_players(team['id'], season_id)
            
            for player in players:
                # Ajouter un délai entre chaque traitement de joueur
                time.sleep(random.uniform(3, 5))
                
                # Vérifier si le joueur existe déjà
                db_player = Player.query.filter_by(api_id=player['id']).first()
                
                if not db_player:
                    # Créer un nouveau joueur
                    db_player = Player(
                        api_id=player['id'],
                        name=player['name'],
                        position=player['position'],
                        club_id=db_team.id
                        # Autres champs...
                    )
                    db.session.add(db_player)
                    db.session.commit()
                    logger.info(f"Joueur créé: {player['name']}")
                
                # Récupérer les statistiques du joueur
                player_stats = self.get_player_stats(player['id'], season_id)
                
                # Créer ou mettre à jour les statistiques du joueur
                db_stats = PlayerStats.query.filter_by(
                    player_id=db_player.id,
                    season=season_id
                ).first()
                
                if not db_stats:
                    db_stats = PlayerStats(
                        player_id=db_player.id,
                        season=season_id
                    )
                    db.session.add(db_stats)
                
                # Mettre à jour les statistiques
                self._update_player_stats(db_stats, player_stats)
                db.session.commit()
                logger.info(f"Statistiques mises à jour pour {player['name']}")
    
    def _update_player_stats(self, db_stats, player_stats):
        """
        Met à jour les statistiques d'un joueur dans la base de données
        
        Args:
            db_stats: l'objet PlayerStats à mettre à jour
            player_stats: les nouvelles statistiques récupérées
        """
        # Mise à jour des statistiques générales
        for key, value in player_stats['summary'].items():
            if hasattr(db_stats, key):
                setattr(db_stats, key, value)
        
        # Conversion des autres catégories de statistiques
        # Cela dépendra de la structure exacte des données et de votre modèle de base de données
        
        # Par exemple, pour les statistiques offensives
        if 'goals' in player_stats['offensive']:
            db_stats.goals = player_stats['offensive']['goals']
        
        if 'assists' in player_stats['offensive']:
            db_stats.assists = player_stats['offensive']['assists']
        
        # Et ainsi de suite pour les autres statistiques...
        
        db_stats.updated_at = datetime.utcnow()