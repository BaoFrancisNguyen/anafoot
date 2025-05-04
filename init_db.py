# init_db.py
from app import db, create_app
import os

# Créer l'application Flask
app = create_app()

# Entrer dans le contexte de l'application
with app.app_context():
    # S'assurer que le répertoire instance existe
    if not os.path.exists('instance'):
        os.makedirs('instance')
    
    # Créer les tables
    db.create_all()
    
    # Afficher un message de confirmation
    print("Base de données initialisée avec succès !")
    print("Tables créées :")
    # Liste les tables créées
    for table in db.metadata.tables.keys():
        print(f" - {table}")