#!/usr/bin/env python3
"""Ajoute une alerte au fil de l'appli (data/alertes.json).

Usage :
  python3 outils/ajoute.py alerte --sources <dossier_export>/appli --balise RUMEUR --titre "..." --texte "..." \
      [--ticker ZS] [--source Bloomberg] [--fiabilite "non confirmé"] [--cle zs-rachat]

Balises : ALERTE, RUMEUR, MOUVEMENT, ARGENT, MACRO, INFO.
--cle evite les doublons : une alerte de meme cle le meme jour n'est pas ajoutee deux fois.
Le script ecrit dans <sources>/alertes.json (en clair, dans la base privee) ; synchro.py
le chiffre ensuite dans le site. Il ne lit rien sur Internet.
"""
import argparse
import datetime
import json
import os
import sys

BALISES = ("ALERTE", "RUMEUR", "MOUVEMENT", "ARGENT", "MACRO", "INFO")
GARDEES = 300


def lis(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def ecris(chemin, objet):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(objet, f, ensure_ascii=False, indent=1)
        f.write("\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="quoi", required=True)
    a = sous.add_parser("alerte")
    a.add_argument("--sources", required=True, help="dossier des sources en clair (<export>/appli)")
    a.add_argument("--balise", required=True, choices=BALISES)
    a.add_argument("--titre", required=True)
    a.add_argument("--texte", default="")
    a.add_argument("--ticker", default="")
    a.add_argument("--source", default="")
    a.add_argument("--fiabilite", default="", choices=("", "confirmé", "non confirmé"))
    a.add_argument("--cle", default="")
    a.add_argument("--heure", default="", help="heure ISO de l'alerte ; maintenant par defaut")
    args = p.parse_args()

    maintenant = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heure = args.heure or maintenant
    chemin = os.path.join(args.sources, "alertes.json")
    alertes = lis(chemin, [])
    if args.cle and any(x.get("cle") == args.cle and (x.get("ts") or "")[:10] == heure[:10] for x in alertes):
        print("deja signale aujourd'hui : %s" % args.cle)
        return 0
    alertes.insert(0, {
        "id": "a" + heure.replace("-", "").replace(":", "").replace("T", "").replace("Z", ""),
        "ts": heure, "balise": args.balise, "titre": args.titre.strip(), "texte": args.texte.strip(),
        "ticker": args.ticker.strip().upper(), "source": args.source.strip(),
        "fiabilite": args.fiabilite, "cle": args.cle,
    })
    alertes.sort(key=lambda x: x.get("ts") or "", reverse=True)
    ecris(chemin, alertes[:GARDEES])
    print("alerte ajoutee : %s" % args.titre)
    return 0


if __name__ == "__main__":
    sys.exit(main())
