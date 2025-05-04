# app/services/whoscored_scraper.py
"""
Module pour extraire les données de fr.whoscored.com en utilisant Selenium
pour gérer le contenu chargé dynamiquement via JavaScript
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
import json
import logging
import random
import os
from bs4 import BeautifulSoup
import pandas as pd
import re
from datetime import datetime

logger = logging.getLogger(__name__)

class WhoScoredSeleniumScraper:
    """
    Scraper utilisant Selenium pour extraire les données de WhoScored
    qui sont chargées dynamiquement via JavaScript
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
    
    def __init__(self, headless=True, chrome_path=None):
        """
        Initialise le scraper Selenium
        
        Args:
            headless: si True, lance Chrome en mode headless (sans interface graphique)
            chrome_path: chemin vers l'exécutable Chrome (optionnel)
        """
        self.options = Options()
        if headless:
            self.options.add_argument('--headless')
        
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--disable-gpu')
        self.options.add_argument('--window-size=1920,1080')
        
        # User-Agent aléatoire
        user_agent = random.choice(self.USER_AGENTS)
        self.options.add_argument(f'user-agent={user_agent}')
        
        # Désactiver les fonctionnalités qui peuvent révéler qu'il s'agit d'un bot
        self.options.add_argument('--disable-blink-features=AutomationControlled')
        self.options.add_experimental_option('excludeSwitches', ['enable-automation'])
        self.options.add_experimental_option('useAutomationExtension', False)
        
        # Ajouter des préférences pour gérer les cookies et autres paramètres
        prefs = {
            "profile.default_content_setting_values.notifications": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False
        }
        self.options.add_experimental_option("prefs", prefs)
        
        try:
            if chrome_path:
                service = Service(executable_path=chrome_path)
                self.driver = webdriver.Chrome(service=service, options=self.options)
            else:
                self.driver = webdriver.Chrome(options=self.options)
            
            # Modifier le navigator.webdriver pour éviter la détection
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # Créer un répertoire pour les captures d'écran si nécessaire
            if not os.path.exists("screenshots"):
                os.makedirs("screenshots")
            
            # Définir des timeouts raisonnables
            self.driver.set_page_load_timeout(30)
            self.wait = WebDriverWait(self.driver, 15)
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de Selenium: {str(e)}")
            raise
    
    def __del__(self):
        """Ferme le navigateur lors de la destruction de l'objet"""
        try:
            if hasattr(self, 'driver'):
                self.driver.quit()
        except:
            pass
    
    def _random_sleep(self, min_seconds=1, max_seconds=3):
        """
        Attend un temps aléatoire entre min_seconds et max_seconds
        """
        time.sleep(random.uniform(min_seconds, max_seconds))
    
    def _simulate_human_behavior(self):
        """
        Simule un comportement humain en effectuant des actions aléatoires
        """
        # Scroll aléatoire
        for _ in range(random.randint(1, 3)):
            scroll_y = random.randint(100, 500)
            self.driver.execute_script(f"window.scrollBy(0, {scroll_y});")
            self._random_sleep(0.5, 1.5)
        
        # Remonter parfois en haut de la page
        if random.random() < 0.3:
            self.driver.execute_script("window.scrollTo(0, 0);")
            self._random_sleep(0.5, 1)
    
    def get_player_detailed_stats(self, player_id, season_id):
        """
        Récupère les statistiques détaillées d'un joueur avec Selenium
        pour accéder aux différents onglets (Defensive, Offensive, Passing, etc.)
        
        Args:
            player_id: l'identifiant du joueur
            season_id: l'identifiant de la saison
        
        Returns:
            Un dictionnaire contenant toutes les statistiques du joueur
        """
        url = f"{self.BASE_URL}/Players/{player_id}/Show/"
        
        # Ajouter des paramètres aléatoires pour éviter la cache
        url = f"{url}?r={random.randint(1000, 9999)}"
        
        try:
            # Ajouter un délai aléatoire avant de charger la page
            self._random_sleep(2, 4)
            
            self.driver.get(url)
            
            # Attendre le chargement initial
            self._random_sleep(3, 5)
            
            # Vérifier si nous sommes redirigés vers une page d'erreur
            if "Error" in self.driver.title or "403" in self.driver.page_source:
                logger.error(f"Détection de page d'erreur ou blocage pour le joueur {player_id}")
                self.driver.save_screenshot(f"screenshots/error_player_{player_id}.png")
                return None
            
            # Simuler un comportement humain
            self._simulate_human_behavior()
            
            # Récupérer les informations de base du joueur
            player_info = self._extract_player_info()
            
            # Récupérer les statistiques de chaque onglet
            stats = {
                'player_id': player_id,
                'season_id': season_id,
                'info': player_info,
                'summary': self._extract_current_tab_stats(),
                'defensive': {},
                'offensive': {},
                'passing': {},
                'detailed': {}
            }
            
            # Liste des onglets à parcourir
            tabs = ['Defensive', 'Offensive', 'Passing', 'Detailed']
            
            for tab_name in tabs:
                try:
                    # Chercher tous les onglets disponibles
                    tab_links = self.driver.find_elements(By.CSS_SELECTOR, ".player-stats-options a")
                    tab = None
                    
                    # Trouver l'onglet correspondant
                    for link in tab_links:
                        if tab_name.lower() in link.text.lower():
                            tab = link
                            break
                    
                    if tab:
                        # Utiliser ActionChains pour un clic plus naturel
                        actions = ActionChains(self.driver)
                        actions.move_to_element(tab).pause(0.3).click().perform()
                        
                        # Attendre après le clic
                        self._random_sleep(2, 3)
                        
                        ## Récupérer les statistiques de l'onglet actuel
                        tab_stats = self._extract_current_tab_stats()
                        stats[tab_name.lower()] = tab_stats
                    else:
                        logger.warning(f"Onglet {tab_name} non trouvé pour le joueur {player_id}")
                except Exception as e:
                    logger.error(f"Erreur lors de l'extraction des statistiques {tab_name} pour le joueur {player_id}: {str(e)}")
                    # Prendre une capture d'écran pour le débogage
                    self.driver.save_screenshot(f"screenshots/error_{player_id}_{tab_name.lower()}.png")
            
            return stats
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des statistiques du joueur {player_id}: {str(e)}")
            # Prendre une capture d'écran pour le débogage
            try:
                self.driver.save_screenshot(f"screenshots/error_player_{player_id}.png")
            except:
                pass
            return None
    
    def _extract_player_info(self):
        """
        Extrait les informations de base du joueur depuis la page actuelle
        """
        try:
            info = {}
            
            # Extraire le nom du joueur
            try:
                player_name_element = self.driver.find_element(By.CSS_SELECTOR, "div.player-header h1")
                info['name'] = player_name_element.text.strip()
            except NoSuchElementException:
                try:
                    # Essayer un sélecteur alternatif
                    player_name_element = self.driver.find_element(By.CSS_SELECTOR, "h1.player-name")
                    info['name'] = player_name_element.text.strip()
                except NoSuchElementException:
                    info['name'] = "Nom non disponible"
                    logger.warning("Nom du joueur non trouvé")
            
            # Extraire d'autres informations comme la position, le club, etc.
            try:
                info_elements = self.driver.find_elements(By.CSS_SELECTOR, "div.player-header dl dt, div.player-header dl dd")
                
                if not info_elements:
                    # Essayer un sélecteur alternatif
                    info_elements = self.driver.find_elements(By.CSS_SELECTOR, "div.player-info dl dt, div.player-info dl dd")
                
                for i in range(0, len(info_elements), 2):
                    if i + 1 < len(info_elements):
                        key = info_elements[i].text.strip().lower().replace(' ', '_').replace(':', '')
                        value = info_elements[i + 1].text.strip()
                        info[key] = value
            except Exception as e:
                logger.warning(f"Erreur lors de l'extraction des informations détaillées du joueur: {str(e)}")
            
            # Prendre une capture d'écran pour référence
            self.driver.save_screenshot(f"screenshots/player_info_{info.get('name', 'unknown').replace(' ', '_')}.png")
            
            return info
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des informations du joueur: {str(e)}")
            return {}
    
    def _extract_current_tab_stats(self):
        """
        Extrait les statistiques de l'onglet actuellement affiché
        """
        try:
            stats = {}
            
            # Attendre que le tableau de statistiques soit chargé
            try:
                # Essayer différents sélecteurs pour trouver le tableau de statistiques
                selectors = [
                    "table.player-statistics",
                    "table.player-stats-detailed",
                    "div.player-stats-container table"
                ]
                
                stats_table = None
                for selector in selectors:
                    try:
                        stats_table = self.wait.until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        if stats_table:
                            break
                    except TimeoutException:
                        continue
                
                if not stats_table:
                    logger.warning("Tableau de statistiques non trouvé")
                    return stats
                
                # Extraire les statistiques
                rows = stats_table.find_elements(By.CSS_SELECTOR, "tbody tr")
                
                for row in rows:
                    cells = row.find_elements(By.CSS_SELECTOR, "td")
                    if len(cells) >= 2:
                        key = cells[0].text.strip().lower().replace(' ', '_').replace('%', 'percent')
                        value = cells[1].text.strip()
                        stats[key] = self._convert_value(value)
            except TimeoutException:
                logger.warning("Timeout en attendant le tableau de statistiques")
            
            # Si aucune statistique n'est trouvée, essayer de lire le HTML brut
            if not stats:
                try:
                    html = self.driver.page_source
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Essayer de trouver le tableau de statistiques
                    tables = soup.select("table.player-statistics, table.player-stats-detailed")
                    
                    for table in tables:
                        rows = table.select("tbody tr")
                        for row in rows:
                            cells = row.select("td")
                            if len(cells) >= 2:
                                key = cells[0].text.strip().lower().replace(' ', '_').replace('%', 'percent')
                                value = cells[1].text.strip()
                                stats[key] = self._convert_value(value)
                except Exception as e:
                    logger.error(f"Erreur lors de l'extraction des statistiques via BeautifulSoup: {str(e)}")
            
            return stats
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des statistiques de l'onglet courant: {str(e)}")
            return {}
    
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
    
    def get_league_player_statistics(self, league_id, season_id, category="Summary"):
        """
        Récupère les statistiques de tous les joueurs d'une ligue pour une catégorie donnée
        
        Args:
            league_id: l'identifiant de la ligue (ex: '252/2' pour Premier League)
            season_id: l'identifiant de la saison
            category: la catégorie de statistiques ('Summary', 'Defensive', 'Offensive', 'Passing', 'Detailed')
        
        Returns:
            Un DataFrame pandas contenant les statistiques des joueurs
        """
        url = f"{self.BASE_URL}/Regions/{league_id}/Tournaments/Seasons/{season_id}/Stages/PlayerStatistics"
        
        # Ajouter des paramètres aléatoires pour éviter la cache
        url = f"{url}?r={random.randint(1000, 9999)}"
        
        try:
            # Ajouter un délai aléatoire avant de charger la page
            self._random_sleep(2, 5)
            
            self.driver.get(url)
            
            # Attendre plus longtemps pour le chargement initial
            self._random_sleep(4, 6)
            
            # Vérifier si nous sommes redirigés vers une page d'erreur
            if "Error" in self.driver.title or "403" in self.driver.page_source:
                logger.error(f"Détection de page d'erreur ou blocage pour la ligue {league_id}")
                # Prendre une capture d'écran pour le débogage
                self.driver.save_screenshot(f"screenshots/error_league_{league_id}.png")
                return None
            
            # Simuler des actions humaines: scroll lent et aléatoire
            self._simulate_human_behavior()
            
            # Cliquer sur l'onglet correspondant à la catégorie demandée
            if category.lower() != "summary":
                try:
                    # Chercher le sélecteur exact pour l'onglet
                    category_tabs = self.driver.find_elements(By.CSS_SELECTOR, "ul.player-filter li a, ul.player-stats-options li a")
                    category_tab = None
                    
                    for tab in category_tabs:
                        if category.lower() in tab.text.lower():
                            category_tab = tab
                            break
                    
                    if category_tab:
                        # Simuler un clic humain avec un petit délai
                        actions = ActionChains(self.driver)
                        actions.move_to_element(category_tab).pause(0.3).click().perform()
                        self._random_sleep(2, 4)
                    else:
                        logger.warning(f"Catégorie {category} non trouvée, utilisation de Summary par défaut")
                except Exception as e:
                    logger.warning(f"Erreur lors du clic sur l'onglet {category}: {str(e)}")
            
            # Attendre l'affichage complet du tableau
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table.player-table-statistics tbody tr, table.stats-table tbody tr"))
                )
            except TimeoutException:
                logger.warning("Timeout en attendant le tableau des statistiques")
            
            # Simuler plus d'actions humaines
            self._simulate_human_behavior()
            
            # Extraire le tableau des statistiques
            try:
                # Essayer différents sélecteurs
                selectors = [
                    "table.player-table-statistics",
                    "table.stats-table"
                ]
                
                table_html = None
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            table_html = elements[0].get_attribute('outerHTML')
                            break
                    except:
                        continue
                
                if not table_html:
                    logger.warning("Aucun tableau de statistiques trouvé")
                    # Sauvegarder la page pour débogage
                    with open(f"screenshots/league_stats_{league_id}_{category.lower()}.html", "w", encoding="utf-8") as f:
                        f.write(self.driver.page_source)
                    self.driver.save_screenshot(f"screenshots/league_stats_{league_id}_{category.lower()}.png")
                    return None
                
                # Prendre une capture d'écran pour le débogage
                self.driver.save_screenshot(f"screenshots/league_stats_{league_id}_{category.lower()}.png")
                
                # Utiliser pandas pour parser le tableau HTML
                dfs = pd.read_html(table_html)
                if dfs and len(dfs) > 0:
                    df = dfs[0]
                    
                    # Nettoyer les noms de colonnes
                    df.columns = [col.strip() for col in df.columns]
                    
                    # Sauvegarder le DataFrame en CSV pour référence
                    csv_path = f"screenshots/league_stats_{league_id}_{category.lower()}.csv"
                    df.to_csv(csv_path, index=False)
                    logger.info(f"Statistiques sauvegardées dans {csv_path}")
                    
                    return df
                else:
                    logger.warning("Aucun tableau de statistiques trouvé par pandas")
                    return None
            except Exception as e:
                logger.error(f"Erreur lors de l'extraction du tableau de statistiques: {str(e)}")
                return None
        
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des statistiques de la ligue {league_id}: {str(e)}")
            try:
                self.driver.save_screenshot(f"screenshots/error_league_{league_id}_{category.lower()}.png")
            except:
                pass
            return None
    
    def get_match_player_statistics(self, match_id):
        """
        Récupère les statistiques détaillées des joueurs pour un match spécifique
        
        Args:
            match_id: l'identifiant du match
        
        Returns:
            Un dictionnaire contenant les statistiques des joueurs pour ce match
        """
        url = f"{self.BASE_URL}/Matches/{match_id}/LiveStatistics"
        
        # Ajouter des paramètres aléatoires pour éviter la cache
        url = f"{url}?r={random.randint(1000, 9999)}"
        
        try:
            # Ajouter un délai aléatoire avant de charger la page
            self._random_sleep(2, 5)
            
            self.driver.get(url)
            
            # Attendre le chargement initial
            self._random_sleep(3, 5)
            
            # Vérifier si nous sommes redirigés vers une page d'erreur
            if "Error" in self.driver.title or "403" in self.driver.page_source:
                logger.error(f"Détection de page d'erreur ou blocage pour le match {match_id}")
                self.driver.save_screenshot(f"screenshots/error_match_{match_id}.png")
                return None
            
            # Simuler un comportement humain
            self._simulate_human_behavior()
            
            # Extraire les informations du match
            match_info = self._extract_match_info()
            
            # Prendre une capture d'écran pour référence
            self.driver.save_screenshot(f"screenshots/match_{match_id}_info.png")
            
            # Extraire les statistiques des joueurs
            player_stats = {
                'home_team': self._extract_team_player_stats('home'),
                'away_team': self._extract_team_player_stats('away')
            }
            
            return {
                'match_id': match_id,
                'info': match_info,
                'player_stats': player_stats
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des statistiques du match {match_id}: {str(e)}")
            try:
                self.driver.save_screenshot(f"screenshots/error_match_{match_id}.png")
            except:
                pass
            return None
    
    def _extract_match_info(self):
        """
        Extrait les informations de base du match depuis la page actuelle
        """
        try:
            info = {}
            
            # Extraire les noms des équipes
            try:
                # Essayer différents sélecteurs
                selectors = [
                    ("div.home-team span.team-name", "div.away-team span.team-name"),
                    ("div.home-team h2", "div.away-team h2"),
                    ("span.home-team-name", "span.away-team-name")
                ]
                
                home_team = None
                away_team = None
                
                for home_selector, away_selector in selectors:
                    try:
                        home_elem = self.driver.find_element(By.CSS_SELECTOR, home_selector)
                        away_elem = self.driver.find_element(By.CSS_SELECTOR, away_selector)
                        if home_elem and away_elem:
                            home_team = home_elem.text.strip()
                            away_team = away_elem.text.strip()
                            break
                    except NoSuchElementException:
                        continue
                
                if home_team and away_team:
                    info['home_team'] = home_team
                    info['away_team'] = away_team
                else:
                    logger.warning("Noms des équipes non trouvés")
            except Exception as e:
                logger.warning(f"Erreur lors de l'extraction des noms des équipes: {str(e)}")
            
            # Extraire le score
            try:
                # Essayer différents sélecteurs
                selectors = [
                    "div.match-centre-header div.result",
                    "div.match-centre-header span.result",
                    "span.match-score"
                ]
                
                score_element = None
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            score_element = elements[0]
                            break
                    except:
                        continue
                
                if score_element:
                    score = score_element.text.strip()
                    info['score'] = score
                else:
                    logger.warning("Score non trouvé")
            except Exception as e:
                logger.warning(f"Erreur lors de l'extraction du score: {str(e)}")
            
            # Extraire la date et l'heure du match
            try:
                # Essayer différents sélecteurs
                selectors = [
                    "div.match-centre-header div.date",
                    "span.match-date",
                    "div.match-info span.date"
                ]
                
                date_element = None
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            date_element = elements[0]
                            break
                    except:
                        continue
                
                if date_element:
                    match_date = date_element.text.strip()
                    info['date'] = match_date
                else:
                    logger.warning("Date du match non trouvée")
            except Exception as e:
                logger.warning(f"Erreur lors de l'extraction de la date: {str(e)}")
            
            return info
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des informations du match: {str(e)}")
            return {}
    
    def _extract_team_player_stats(self, team_type):
        """
        Extrait les statistiques des joueurs pour une équipe (domicile ou extérieur)
        
        Args:
            team_type: 'home' ou 'away'
        """
        try:
            # Cliquer sur l'onglet des statistiques des joueurs
            try:
                # Essayer différents sélecteurs
                selectors = [
                    "//a[contains(text(), 'Player Statistics')]",
                    "//a[contains(text(), 'Statistiques des joueurs')]",
                    "//a[contains(@class, 'player-stats-tab')]"
                ]
                
                player_stats_tab = None
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.XPATH, selector)
                        if elements:
                            player_stats_tab = elements[0]
                            break
                    except:
                        continue
                
                if player_stats_tab:
                    # Utiliser ActionChains pour un clic plus naturel
                    actions = ActionChains(self.driver)
                    actions.move_to_element(player_stats_tab).pause(0.3).click().perform()
                    self._random_sleep(1, 3)
                else:
                    logger.warning("Onglet des statistiques des joueurs non trouvé")
                    return []
            except Exception as e:
                logger.warning(f"Erreur lors du clic sur l'onglet des statistiques des joueurs: {str(e)}")
                return []
            
            # Sélectionner l'onglet de l'équipe appropriée
            try:
                # Essayer différents sélecteurs
                selectors = [
                    f"//a[contains(@class, '{team_type}-tab')]",
                    f"//a[contains(@data-team-type, '{team_type}')]",
                    f"//li[contains(@class, '{team_type}')]/a"
                ]
                
                team_tab = None
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.XPATH, selector)
                        if elements:
                            team_tab = elements[0]
                            break
                    except:
                        continue
                
                if team_tab:
                    # Utiliser ActionChains pour un clic plus naturel
                    actions = ActionChains(self.driver)
                    actions.move_to_element(team_tab).pause(0.3).click().perform()
                    self._random_sleep(1, 3)
                else:
                    logger.warning(f"Onglet de l'équipe {team_type} non trouvé")
                    return []
            except Exception as e:
                logger.warning(f"Erreur lors du clic sur l'onglet de l'équipe {team_type}: {str(e)}")
                return []
            
            # Extraire le tableau des statistiques
            try:
                # Essayer différents sélecteurs
                selectors = [
                    f"div.{team_type}-team-statistics table.player-statistics",
                    f"div.{team_type}-team-stats table.player-statistics",
                    f"div.{team_type}-team-statistics table"
                ]
                
                table_html = None
                for selector in selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            table_html = elements[0].get_attribute('outerHTML')
                            break
                    except:
                        continue
                
                if not table_html:
                    logger.warning(f"Aucun tableau de statistiques trouvé pour l'équipe {team_type}")
                    self.driver.save_screenshot(f"screenshots/match_team_{team_type}_no_table.png")
                    return []
                
                # Prendre une capture d'écran pour référence
                self.driver.save_screenshot(f"screenshots/match_team_{team_type}_stats.png")
                
                # Utiliser pandas pour parser le tableau HTML
                dfs = pd.read_html(table_html)
                if dfs and len(dfs) > 0:
                    df = dfs[0]
                    
                    # Convertir le DataFrame en dictionnaire
                    players_stats = []
                    
                    for _, row in df.iterrows():
                        player_stats = {col: row[col] for col in df.columns}
                        players_stats.append(player_stats)
                    
                    return players_stats
                else:
                    logger.warning(f"Aucun tableau de statistiques trouvé par pandas pour l'équipe {team_type}")
                    return []
            except Exception as e:
                logger.error(f"Erreur lors de l'extraction du tableau de statistiques pour l'équipe {team_type}: {str(e)}")
                return []
        except Exception as e:
            logger.error(f"Erreur lors de l'extraction des statistiques des joueurs de l'équipe {team_type}: {str(e)}")
            return []

    def get_league_teams(self, league_id, season_id):
        """
        Récupère la liste des équipes pour une ligue et une saison données en utilisant Selenium
        """
        url = f"{self.BASE_URL}/Regions/{league_id}/Tournaments/Seasons/{season_id}/Stages/"
        
        try:
            self._random_sleep(2, 5)
            self.driver.get(url)
            self._random_sleep(3, 5)
            
            # Vérifier les erreurs
            if "Error" in self.driver.title or "403" in self.driver.page_source:
                logger.error(f"Détection de page d'erreur ou blocage pour la ligue {league_id}")
                self.driver.save_screenshot(f"screenshots/error_league_{league_id}.png")
                return []
            
            # Simuler un comportement humain
            self._simulate_human_behavior()
            
            # Extraire les équipes
            teams = []
            selectors = [
                'table.standings a[href*="/Teams/"]',
                'div.tournament-teamlist a[href*="/Teams/"]'
            ]
            
            for selector in selectors:
                team_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if team_elements:
                    for element in team_elements:
                        href = element.get_attribute('href')
                        if href and '/Teams/' in href:
                            team_id = href.split('/')[4]  # Adapter selon structure URL
                            team_name = element.text.strip()
                            teams.append({
                                'id': team_id,
                                'name': team_name,
                                'league_id': league_id,
                                'season_id': season_id
                            })
                    break  # Sortir de la boucle si des équipes ont été trouvées
            
            # Sauvegarder un screenshot pour débogage
            self.driver.save_screenshot(f"screenshots/league_teams_{league_id}.png")
            
            return teams
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des équipes de la ligue {league_id}: {str(e)}")
            return []