#!/usr/bin/env python3
"""Rafraichit les cours et envoie les alertes automatiques, sans Claude (lance par GitHub jour et nuit ; chaque tache tourne 10 minutes et refait un passage chaque minute).

- Lit data/suivi.json (tickers a suivre, ecrit par synchro.py) et data/polymarket.json (marches suivis).
- Ecrit data/cours.json, chiffre avec la cle publique (comme les autres donnees).
- Veille des titres de grands medias (flux publics, sans IA) : alerte si un titre recent contient une expression grave
  (nucleaire, guerre, attentat, coupe-circuit, baisse des taux en urgence...).
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
    with urllib.request.urlopen(req, timeout=8) as r:
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


# ---------- Veille des titres d'actualite (sans IA), chaque minute ----------
# Deux niveaux, pour alerter vite sans inonder :
#  1) GRAVES : une expression grave seule suffit (nucleaire, bombe, attentat, president tue...).
#  2) SUJET + EVENEMENT : un nom suivi (Nvidia, Nasdaq, argent, Fed...) avec un verbe fort (plonge, s'envole,
#     enquete, demission...). Un nom seul ou un mot courant seul (« guerre » : il y en a tous les jours) ne suffit pas.
# Une meme idee (sujet + sens) n'est envoyee qu'une fois par tranche de 3 heures, quelle que soit la source.
FLUX = [
    ("Google News", "https://news.google.com/rss/search?q=when:1h+(nuclear+OR+missile+OR+war+OR+attack+OR+bomb+OR+invasion+OR+president+OR+%22emergency%22+OR+%22trading+halted%22+OR+plunge+OR+soar+OR+crash)&hl=en-US&gl=US&ceid=US:en"),
    ("Google News", "https://news.google.com/rss/search?q=when:1h+(Nvidia+OR+Tesla+OR+Apple+OR+Microsoft+OR+Amazon+OR+Alphabet+OR+Google+OR+Meta+OR+Nasdaq+OR+silver+OR+gold+OR+Fed+OR+Powell+OR+Trump+OR+tariff)&hl=en-US&gl=US&ceid=US:en"),
    ("Google News FR", "https://news.google.com/rss/search?q=when:1h+(nucl%C3%A9aire+OR+missile+OR+guerre+OR+attaque+OR+attentat+OR+bombe+OR+invasion+OR+pr%C3%A9sident+OR+CAC+OR+krach)&hl=fr&gl=FR&ceid=FR:fr"),
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC Marchés", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("Fed", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("BCE", "https://www.ecb.europa.eu/rss/press.html"),
    ("Le Monde", "https://www.lemonde.fr/international/rss_full.xml"),
    ("Le Monde Éco", "https://www.lemonde.fr/economie/rss_full.xml"),
]
GUERRE = "indices vont baisser, or et argent vont monter"
CRISE = "indices vont baisser, or va monter"
GRAVES = [  # (expression en minuscules, fait court, consequence)
    ("nuclear strike", "Frappe nucléaire", GUERRE), ("nuclear attack", "Attaque nucléaire", GUERRE), ("nuclear weapon", "Arme nucléaire", GUERRE),
    ("nuclear bomb", "Bombe nucléaire", GUERRE), ("frappe nucléaire", "Frappe nucléaire", GUERRE), ("attaque nucléaire", "Attaque nucléaire", GUERRE),
    ("bombe nucléaire", "Bombe nucléaire", GUERRE), ("arme nucléaire", "Arme nucléaire", GUERRE),
    ("declares war", "Déclaration de guerre", GUERRE), ("déclare la guerre", "Déclaration de guerre", GUERRE), ("state of war", "État de guerre", GUERRE),
    ("invades", "Invasion", GUERRE), ("invasion of", "Invasion", GUERRE), ("invasion de", "Invasion", GUERRE),
    ("missile strike", "Frappe de missiles", GUERRE), ("missiles hit", "Frappe de missiles", GUERRE), ("frappe de missile", "Frappe de missiles", GUERRE),
    ("attack on", "Attaque", CRISE), ("attacked", "Attaque", CRISE), ("attaque contre", "Attaque", CRISE), ("attaqué", "Attaque", CRISE),
    ("bombing", "Bombardement", CRISE), ("bombardement", "Bombardement", CRISE), ("bomb ", "Bombe", CRISE), ("bombe ", "Bombe", CRISE),
    ("explosion at", "Explosion", CRISE), ("explosion à", "Explosion", CRISE), ("drone attack", "Attaque de drones", CRISE),
    ("blockade of taiwan", "Blocus de Taïwan", GUERRE), ("taiwan blockade", "Blocus de Taïwan", GUERRE), ("blocus de taïwan", "Blocus de Taïwan", GUERRE),
    ("strait of hormuz", "Détroit d'Ormuz", "pétrole et or vont monter, indices vont baisser"), ("détroit d'ormuz", "Détroit d'Ormuz", "pétrole et or vont monter, indices vont baisser"),
    ("terror attack", "Attentat", CRISE), ("terrorist attack", "Attentat", CRISE), ("attentat", "Attentat", CRISE),
    ("martial law", "Loi martiale", CRISE), ("loi martiale", "Loi martiale", CRISE), ("coup d'état", "Coup d'État", CRISE), ("military coup", "Coup d'État", CRISE),
    ("assassinated", "Assassinat", CRISE), ("assassination", "Assassinat", CRISE), ("assassiné", "Assassinat", CRISE),
    ("president shot", "Président visé par des tirs", CRISE), ("president killed", "Président tué", CRISE), ("president dies", "Mort du président", CRISE),
    ("president dead", "Mort du président", CRISE), ("president hospitalized", "Président hospitalisé", CRISE), ("president resigns", "Démission du président", CRISE),
    ("président tué", "Président tué", CRISE), ("mort du président", "Mort du président", CRISE), ("président hospitalisé", "Président hospitalisé", CRISE),
    ("démission du président", "Démission du président", CRISE), ("cyberattack on", "Cyberattaque", CRISE), ("cyberattaque contre", "Cyberattaque", CRISE),
    ("emergency rate cut", "Baisse des taux en urgence", "indices vont baisser à court terme, or va monter"),
    ("emergency meeting", "Réunion d'urgence", "indices vont bouger fort, or va monter"), ("réunion d'urgence", "Réunion d'urgence", "indices vont bouger fort, or va monter"),
    ("trading halted", "Cotations suspendues", "indices vont baisser"), ("trading halt", "Cotations suspendues", "indices vont baisser"),
    ("circuit breaker", "Coupe-circuit déclenché", "indices vont baisser"), ("market crash", "Krach", CRISE), ("krach", "Krach", CRISE),
    ("bank run", "Panique bancaire", CRISE), ("bank collapse", "Faillite bancaire", CRISE), ("faillite bancaire", "Faillite bancaire", CRISE),
    ("sovereign default", "Défaut d'un État", CRISE), ("défaut de paiement", "Défaut de paiement", CRISE),
]
SUJETS = [  # (mots qui le designent, nom affiche)
    (("nvidia",), "Nvidia"), (("tesla",), "Tesla"), (("apple ", "apple's", "iphone"), "Apple"), (("microsoft",), "Microsoft"),
    (("amazon",), "Amazon"), (("alphabet", "google"), "Google"), (("meta platforms", "meta's", "facebook"), "Meta"), (("netflix",), "Netflix"),
    (("broadcom",), "Broadcom"), (("tsmc",), "TSMC"), ((" amd ", "amd's"), "AMD"), (("palantir",), "Palantir"), (("openai",), "OpenAI (Microsoft)"),
    (("robot", "humanoid", "optimus"), "Robotique"), (("nasdaq",), "Nasdaq"), (("s&p 500", "s&p500", "wall street", "stocks", "dow jones"), "Wall Street"),
    (("cac 40", "cac40", "bourse de paris"), "CAC 40"), (("dax",), "DAX"), (("nikkei",), "Nikkei"),
    (("silver", "cours de l'argent"), "Argent"), (("gold ", "gold price", "prix de l'or", "l'or "), "Or"),
    (("fed ", "federal reserve", "powell", "fomc"), "Fed"), (("ecb", "bce", "lagarde"), "BCE"), (("bank of japan", "boj"), "Banque du Japon"),
    (("trump", "white house", "maison blanche"), "Maison Blanche"), (("tariff", "droits de douane"), "Droits de douane"),
]
HAUT = ("soar", "surge", "skyrocket", "jumps", "rallies", "record high", "all-time high", "beats", "raises guidance", "rate cut",
        "cuts rates", "pauses tariffs", "lifts tariffs", "s'envole", "bondit", "flambe", "record historique", "baisse des taux")
BAS = ("plunge", "plummet", "tumble", "crash", "sinks", "slump", "halted", "probe", "investigation", "subpoena", "antitrust", "recall",
       "lawsuit", "misses", "cuts guidance", "warns", "downgrade", "resigns", "steps down", "dies", "fraud", "bankrupt", "ban ",
       "rate hike", "raises rates", "imposes tariffs", "new tariffs", "hikes tariffs", "export ban", "export curbs",
       "plonge", "s'effondre", "chute", "dégringole", "enquête", "démission", "fraude", "faillite", "interdiction", "hausse des taux", "sanction")
DOUTE = ("fear", "threat", "warn of", "could", "would", "might", "may ", "risk", "if ", "deny", "denies", "rule out", "talks", "treaty",
         "anniversary", "drill", "exercise", "film", "movie", "game", "review:", "opinion", "analysis", "explainer", "how to", "what to know",
         "craint", "menace", "pourrait", "risque", "si ", "dément", "négociation", "traité", "exercice", "anniversaire", "tribune", "?")


def lis_flux(source, url):
    import email.utils
    import xml.etree.ElementTree as ET
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=8) as r:
        racine = ET.fromstring(r.read())
    for item in racine.iter("item"):
        titre = (item.findtext("title") or "").strip()
        try:
            quand = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "")
            if quand.tzinfo is None:
                quand = quand.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            continue
        yield titre, quand, item.findtext("link") or ""


def classe(titre, source):
    """Renvoie (cle de regroupement, fait, consequence) ou None."""
    bas = " " + titre.lower() + " "
    if any(d in bas for d in DOUTE):
        return None
    for expr, fait, consequence in GRAVES:
        if expr in bas:
            if source == "Fed" and expr not in ("emergency rate cut", "emergency meeting"):
                return None
            return "grave|" + fait, fait, consequence
    for mots, nom in SUJETS:
        if any(m in bas for m in mots):
            haut, baisse = any(m in bas for m in HAUT), any(m in bas for m in BAS)
            if haut == baisse:  # aucun verbe fort, ou les deux : pas d'alerte
                return None
            sens = "monter" if haut else "baisser"
            court = titre.rsplit(" - ", 1)[0]
            if nom in ("Fed", "BCE", "Banque du Japon", "Maison Blanche", "Droits de douane"):
                consequence = "indices vont " + sens
            elif nom == "Robotique":
                consequence = "valeurs de la robotique vont " + sens
            else:
                consequence = nom + " va " + sens
            return "sujet|%s|%s" % (nom, sens), court[:70], consequence
    return None


def flashs(maintenant):
    vus, sortie = set(), []
    for source, url in FLUX:
        try:
            items = list(lis_flux(source, url))
        except Exception as e:
            print("flux", source, "indisponible :", e)
            continue
        for titre, quand, lien in items:
            bas = titre.lower()
            if not titre or bas in vus or (maintenant - quand).total_seconds() > 90 * 60:
                continue
            vus.add(bas)
            c = classe(titre, source)
            if c:
                sortie.append({"cle": c[0], "fait": c[1], "consequence": c[2], "titre": titre[:200], "source": source,
                               "heure": quand.strftime("%Y-%m-%dT%H:%M:%SZ"), "lien": lien})
    sortie.sort(key=lambda f: f["heure"], reverse=True)
    return sortie[:30]


def envoie(titre, texte, tag):
    cle, abos = os.environ.get("VAPID_PRIVEE"), os.environ.get("PUSH_ABONNEMENTS")
    if not cle or not abos:
        print("pas de secrets d'envoi : alerte non envoyée :", titre, texte)
        return
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush
    vapid = Vapid.from_string(cle)
    abonnements = json.loads(abos)
    if isinstance(abonnements, dict):
        abonnements = [abonnements]
    charge = json.dumps({"title": titre, "body": texte[:300], "tag": tag, "url": "./"}, ensure_ascii=False)
    for ab in abonnements:
        try:
            webpush(subscription_info=ab, data=charge, vapid_private_key=vapid,
                    vapid_claims={"sub": "https://leo-52.github.io"}, ttl=3 * 3600, headers={"Urgency": "high"})
            print("envoyé :", titre)
        except WebPushException as e:
            print("échec d'envoi :", getattr(e.response, "status_code", None), str(e)[:200])
        except Exception as e:  # un envoi raté ne doit jamais faire échouer la relève des cours
            print("échec d'envoi :", e)


def tour(etat, suivi, marches, deja):
    """Un passage complet : cours, Polymarket, titres. Renvoie (sortie, nombre de nouvelles alertes envoyees)."""
    maintenant = datetime.datetime.now(datetime.timezone.utc)
    jour = maintenant.strftime("%Y-%m-%d")
    sortie = {"maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"), "indices": {}, "titres": {}, "polymarket": [], "flash": []}
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
            alertes.append(("%s|%s|%d" % (s, c["heure"][:10], int(abs(c["var"]) // seuil)), "Alerte", "%s %+.1f %% à %s" % (nom, c["var"], ("%.2f" % c["prix"]).replace(".", ","))))
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
            alertes.append(("%s|%s|%d" % (t, c["heure"][:10], palier), "Alerte", "%s %+.1f %% à %s $ dans la séance" % (t, c["var"], ("%.2f" % c["prix"]).replace(".", ","))))
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
    tranche = "%s-%d" % (jour, maintenant.hour // 3)  # une meme idee une fois par tranche de 3 heures
    for f in flashs(maintenant):
        sortie["flash"].append(f)
        alertes.append((f["cle"] + "|" + tranche, f["fait"], "Conséquence : " + f["consequence"] + " · " + f["source"]))
    a_envoyer = []
    for cle, titre, texte in alertes:
        h = hashlib.sha256(cle.encode()).hexdigest()[:16]
        if h in deja:
            continue
        deja.add(h)
        etat["envoyees"].append([h, jour])
        a_envoyer.append((titre, texte))
    nouvelles = len(a_envoyer)
    if nouvelles > 3:  # jamais plus de 3 notifications d'un coup : le reste regroupe en une seule
        reste = a_envoyer[2:]
        a_envoyer = a_envoyer[:2] + [("%d autres alertes" % len(reste), " · ".join(t for t, _ in reste))]
    for titre, texte in a_envoyer:
        try:
            envoie(titre, texte, "auto")
        except Exception as e:
            print("envoi impossible :", e)
    print("%s : %d indices, %d titres, %d marchés Polymarket, %d titres d'actualité retenus, %d nouvelles alertes" % (
        sortie["maj"], len(sortie["indices"]), len(sortie["titres"]), len(sortie["polymarket"]), len(sortie["flash"]), nouvelles))
    return sortie, nouvelles


def main():
    """Tourne MINUTES minutes (variable d'environnement, 1 par defaut) en refaisant un passage chaque minute."""
    import time
    data = os.path.join(SITE, "data")
    suivi = lis(os.path.join(data, "suivi.json"), {"tickers": []})
    marches = lis(os.path.join(data, "polymarket.json"), {"marches": []})
    etat = lis(os.path.join(data, "auto_etat.json"), {"envoyees": [], "poly": {}})
    debut = datetime.datetime.now(datetime.timezone.utc)
    etat.pop("jour", None)
    etat.setdefault("poly", {})
    limite = (debut - datetime.timedelta(days=3)).strftime("%Y-%m-%d")
    etat["envoyees"] = [x for x in etat.get("envoyees", []) if isinstance(x, list) and x[1] >= limite]
    deja = {x[0] for x in etat["envoyees"]}
    minutes = int(os.environ.get("MINUTES", "1"))
    fin = time.time() + minutes * 60 - 50  # s'arrete toujours a l'heure, meme si une source est lente
    sortie = None
    i = 0
    while True:
        t0 = time.time()
        try:
            sortie, _ = tour(etat, suivi, marches, deja)
        except Exception as e:  # un passage rate ne doit pas arreter les suivants
            print("passage raté :", e)
        # l'etat est ecrit a chaque passage : si GitHub coupe la tache, rien n'est renvoye deux fois
        ecris(os.path.join(data, "auto_etat.json"), etat)
        if sortie:
            coffre.ecris_donnee(SITE, "cours", sortie, coffre.cle_publique(SITE))
        i += 1
        if time.time() + 60 > fin:
            break
        time.sleep(max(0, 60 - (time.time() - t0)))
    print("%d passages" % i)


if __name__ == "__main__":
    main()
