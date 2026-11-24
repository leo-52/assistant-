# Bourse — mini appli

Appli web à installer sur l'écran d'accueil : alertes, points de la journée, prédictions, score et agenda.

- `index.html`, `sw.js`, `manifest.webmanifest`, `icones/` : l'appli (aucune dépendance, aucun serveur).
- `data/*.json` : les données affichées, **chiffrées** (RSA-OAEP 3072 + AES-256-GCM). `data/cle.json` contient la clé publique et la clé privée chiffrée par le mot de passe (PBKDF2-SHA256, 600 000 tours). Le déchiffrement se fait dans le navigateur ; le mot de passe n'est stocké nulle part.
- Tant que `data/cle.json` n'existe pas, l'appli propose de créer le mot de passe.
- `outils/coffre.py` : chiffrement avec la clé publique (les scripts ne connaissent jamais le mot de passe).
- `outils/synchro.py <export>` : refabrique prédictions, score, points et agenda depuis un export de la base du Journal.
- `outils/ajoute.py alerte --sources <export>/appli …` : ajoute une alerte aux sources en clair (base privée) ; `synchro.py` la chiffre dans le site.

Aucune donnée personnelle : ni nom, ni positions, ni montants.
