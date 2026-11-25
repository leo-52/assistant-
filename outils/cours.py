#!/usr/bin/env python3
"""Rafraichit les cours et envoie les alertes automatiques, sans Claude (lance par GitHub toutes les 10 minutes).

- Lit data/suivi.json (tickers a suivre, ecrit par synchro.py) et data/polymarket.json (marches suivis).
- Ecrit data/cours.json, chiffre avec la cle publique (comme les autres donnees).
- Alerte (notification de l'appli) si : un titre suivi bouge de 8 % ou plus dans la seance, un indice suivi de 2 %,
  l'argent de 3 %, l'or de 2 %, ou une cote Polymarket suivie de 15 points depuis l'alerte precedente.
- Les secrets VAPID_PRIVEE et PUSH_ABONNEMENTS (reglages du depot GitHub) servent a l'envoi ; sans eux, pas d'envoi.
- data/auto_etat.json garde seulement des empreintes des alertes deja envoyees (rien de lisible).
"""
import datetime
import hashlib
import json
import os
import sys
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ICI, "..")
sys.path.insert(0, ICI)
import coffre  # noqa: E402

INDICES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^FCHI": "CAC 40", "^GDAXI": "DAX", "^N225": "Nikkei",
           "SI=F": "Argent", "GC=F": "Or"}
SEUILS = {"titre": 8.0, "indice": 2.0, "SI=F": 3.0, "GC=F": 2.0}
UA = {"User-Agent": "Mozilla/5.0 (assistant leo)"}


def lis(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def ecris(chemin, objet):
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(objet, f, ensure_ascii=False, indent=1)
        f.write("\n")


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def cours(symbole):
    d = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m" % urllib.request.quote(symbole))
    m = d["chart"]["result"][0]["meta"]
    prix, veille = m.get("regularMarketPrice"), m.get("chartPreviousClose") or m.get("previousClose")
    if prix is None or not veille:
        return None
    return {"prix": round(prix, 4), "veille": round(veille, 4), "var": round((prix / veille - 1) * 100, 2),
            "heure": datetime.datetime.fromtimestamp(m.get("regularMarketTime", 0), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def polymarket(slug):
    d = get_json("https://gamma-api.polymarket.com/markets?slug=" + urllib.request.quote(slug))
    if not d:
        return None
    m = d[0]
    prix = json.loads(m.get("outcomePrices") or "[]")
    issues = json.loads(m.get("outcomes") or "[]")
    if not prix:
        return None
    return {"question": m.get("question"), "issues": issues, "cotes": [round(float(p) * 100) for p in prix]}


def envoie(titre, texte, tag):
    cle, abos = os.environ.get("VAPID_PRIVEE"), os.environ.get("PUSH_ABONNEMENTS")
    if not cle or not abos:
        print("pas de secrets d'envoi : alerte non envoyée :", titre, texte)
        return
    import base64
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush
    vapid = Vapid.from_raw(base64.urlsafe_b64decode(cle + "=" * (-len(cle) % 4)))
    abonnements = json.loads(abos)
    if isinstance(abonnements, dict):
        abonnements = [abonnements]
    charge = json.dumps({"title": titre, "body": texte[:300], "tag": tag, "url": "./"}, ensure_ascii=False)
    for ab in abonnements:
        try:
            webpush(subscription_info=ab, data=charge, vapid_private_key=vapid,
                    vapid_claims={"sub": "https://leo-52.github.io/assistant-/"}, ttl=3 * 3600)
            print("envoyé :", titre)
        except WebPushException as e:
            print("échec d'envoi :", getattr(e.response, "status_code", None))


def main():
    data = os.path.join(SITE, "data")
    suivi = lis(os.path.join(data, "suivi.json"), {"tickers": []})
    marches = lis(os.path.join(data, "polymarket.json"), {"marches": []})
    etat = lis(os.path.join(data, "auto_etat.json"), {"jour": "", "envoyees": [], "poly": {}})
    maintenant = datetime.datetime.now(datetime.timezone.utc)
    jour = maintenant.strftime("%Y-%m-%d")
    if etat.get("jour") != jour:
        etat = {"jour": jour, "envoyees": [], "poly": etat.get("poly", {})}
    deja = set(etat["envoyees"])
    sortie = {"maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), "indices": {}, "titres": {}, "polymarket": []}
    alertes = []
    for s, nom in INDICES.items():
        try:
            c = cours(s)
        except Exception as e:  # une source qui tombe ne bloque pas le reste
            print("cours", s, "indisponible :", e)
            continue
        if not c:
            continue
        c["nom"] = nom
        sortie["indices"][s] = c
        seuil = SEUILS.get(s, SEUILS["indice"])
        if abs(c["var"]) >= seuil:
            alertes.append(("%s|%d" % (s, int(abs(c["var"]) // seuil)), "Alerte", "%s %+.1f %% à %s" % (nom, c["var"], ("%.2f" % c["prix"]).replace(".", ","))))
    for t in suivi.get("tickers", [])[:40]:
        try:
            c = cours(t)
        except Exception as e:
            print("cours", t, "indisponible :", e)
            continue
        if not c:
            continue
        sortie["titres"][t] = c
        if abs(c["var"]) >= SEUILS["titre"]:
            palier = 1 if abs(c["var"]) < 15 else 2 if abs(c["var"]) < 25 else 3
            alertes.append(("%s|%d" % (t, palier), "Alerte", "%s %+.1f %% à %s $ dans la séance" % (t, c["var"], ("%.2f" % c["prix"]).replace(".", ","))))
    for mk in marches.get("marches", [])[:20]:
        slug = mk.get("slug") if isinstance(mk, dict) else mk
        try:
            p = polymarket(slug)
        except Exception as e:
            print("polymarket", slug, "indisponible :", e)
            continue
        if not p:
            continue
        p["slug"] = slug
        p["libelle"] = mk.get("libelle") if isinstance(mk, dict) else None
        sortie["polymarket"].append(p)
        ref = etat["poly"].get(slug)
        oui = p["cotes"][0]
        if ref is None:
            etat["poly"][slug] = oui
        elif abs(oui - ref) >= 15:
            alertes.append(("poly|%s|%d" % (slug, oui), "Polymarket", "%s : %s %d %% (était %d %%)" % (p["libelle"] or p["question"], p["issues"][0] if p["issues"] else "oui", oui, ref)))
            etat["poly"][slug] = oui
    for cle, titre, texte in alertes:
        h = hashlib.sha256(cle.encode()).hexdigest()[:16]
        if h in deja:
            continue
        envoie(titre, texte, "auto")
        deja.add(h)
    etat["envoyees"] = sorted(deja)
    coffre.ecris_donnee(SITE, "cours", sortie, coffre.cle_publique(SITE))
    ecris(os.path.join(data, "auto_etat.json"), etat)
    print("cours : %d indices, %d titres, %d marchés Polymarket, %d alertes" % (len(sortie["indices"]), len(sortie["titres"]), len(sortie["polymarket"]), len(alertes)))


if __name__ == "__main__":
    main()
