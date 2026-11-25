#!/usr/bin/env python3
"""Envoie une notification de l'appli Assistant a chaque telephone abonne (Web Push).

Usage : python3 outils/notifie.py --abonnements abonnements.json --vapid vapid.json \
            --titre "Matin" --texte "S&P +0,4 % ..." [--tag matin]

abonnements.json : liste des abonnements copies depuis le Menu de l'appli.
vapid.json : {"publique": ..., "privee": ..., "sujet": ...} (cle privee : jamais dans le depot).
Necessite le paquet pywebpush. Sortie : une ligne par telephone, « envoyé » ou l'erreur.
"""
import argparse
import json
import sys

SUJET = "https://leo-52.github.io"  # py_vapid refuse un sujet avec un chemin

from py_vapid import Vapid
from pywebpush import WebPushException, webpush


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--abonnements", required=True)
    p.add_argument("--vapid", required=True)
    p.add_argument("--titre", required=True)
    p.add_argument("--texte", required=True)
    p.add_argument("--tag", default="assistant")
    p.add_argument("--url", default="./")
    a = p.parse_args()
    abonnements = json.load(open(a.abonnements, encoding="utf-8"))
    if isinstance(abonnements, dict):
        abonnements = [abonnements]
    cle = json.load(open(a.vapid, encoding="utf-8"))
    vapid = Vapid.from_string(cle["privee"])  # from_raw donnait une autre cle (Apple : VapidPkHashMismatch)
    charge = json.dumps({"title": a.titre[:60], "body": a.texte[:300], "tag": a.tag, "url": a.url}, ensure_ascii=False)
    ok = 0
    for i, ab in enumerate(abonnements, 1):
        try:
            webpush(subscription_info=ab, data=charge, vapid_private_key=vapid,
                    vapid_claims={"sub": SUJET}, ttl=6 * 3600)
            print("telephone %d : envoyé" % i)
            ok += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            print("telephone %d : erreur %s %s" % (i, code, str(e)[:200]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
