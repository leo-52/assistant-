# Bourse — mini appli

Appli web à installer sur l'écran d'accueil : alertes, points de la journée, prédictions, score et agenda.

- `index.html`, `sw.js`, `manifest.webmanifest`, `icones/` : l'appli (aucune dépendance, aucun serveur).
- `data/*.json` : les données affichées. Elles sont écrites par les robots, jamais à la main.
- `outils/synchro.py <export>` : refabrique prédictions, score, points et agenda depuis un export de la base du Journal.
- `outils/ajoute.py alerte …` : ajoute une alerte au fil.

Aucune donnée personnelle : ni nom, ni positions, ni montants.
