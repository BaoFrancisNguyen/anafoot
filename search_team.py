from app import create_app
import requests
import json

app = create_app()

def search_team(team_name):
    """
    Recherche une équipe par son nom via API-Football
    
    Args:
        team_name: Le nom de l'équipe à rechercher
        
    Returns:
        Liste des équipes correspondantes
    """
    with app.app_context():
        # Récupérer la clé API depuis la configuration
        api_key = app.config['API_FOOTBALL_KEY']
        
        # URL de l'API
        url = "https://v3.football.api-sports.io/teams"
        
        # Paramètres de recherche
        params = {
            "search": team_name
        }
        
        # En-têtes avec authentification
        headers = {
            'x-rapidapi-key': api_key,
            'x-rapidapi-host': 'api-football-v1.p.rapidapi.com'
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'response' in data and len(data['response']) > 0:
                    teams = data['response']
                    return teams
                else:
                    print(f"Aucune équipe trouvée pour '{team_name}'")
                    return []
            else:
                print(f"Erreur API: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            print(f"Erreur lors de la recherche: {str(e)}")
            return []

def main():
    """
    Fonction principale qui demande le nom d'une équipe et affiche les résultats
    """
    team_name = input("Entrez le nom de l'équipe à rechercher: ")
    
    if not team_name:
        print("Nom d'équipe vide, recherche annulée.")
        return
    
    print(f"Recherche de l'équipe '{team_name}'...")
    teams = search_team(team_name)
    
    if teams:
        print(f"\nRésultats ({len(teams)} équipes trouvées):")
        print("ID | Nom | Pays | Fondée | Stade")
        print("-" * 80)
        
        for team in teams:
            team_info = team['team']
            venue_info = team.get('venue', {})
            
            print(f"{team_info['id']} | {team_info['name']} | {team_info.get('country', 'N/A')} | "
                  f"{team_info.get('founded', 'N/A')} | {venue_info.get('name', 'N/A')}")
    else:
        print("Aucune équipe trouvée.")

if __name__ == "__main__":
    main()