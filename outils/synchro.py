#!/usr/bin/env python3
"""Fabrique les fichiers data/*.json de l'appli a partir d'un export de la base du Journal.

Usage : python3 outils/synchro.py <dossier_export> [dossier_du_site]

Si <site>/data/cle.json existe, chaque fichier de donnees est chiffre avec la cle publique.
<dossier_export>/appli/ contient les sources en clair : points.json (archive, mise a jour par
ce script), alertes.json (ecrit par ajoute.py) et argent.json.

<dossier_export> contient journal/*.json (une ligne du Journal par fichier) et
meta/*.json (fil_matin, fil_ouverture, fil_point, fil_cloture, fil_prep, fil_scan, banc),
tels que l'outil ArtifactData les ecrit avec out_dir.
Le script ne lit rien sur Internet et n'ecrit que dans <site>/data/ et <dossier_export>/appli/.
"""
import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coffre  # noqa: E402

PLAT = 0.5          # |gap| < 0,5 % = plat (definition du classeur)
JOURS_GARDES = 21   # profondeur de l'onglet Predictions
POINTS_GARDES = 150
OBJECTIF = 30       # nombre de predictions tranchees avant le verdict de la regle
REGLE = "v3.8"
JOURS = ["LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI", "SAMEDI", "DIMANCHE", "WEEK-END"]
NOMS = {"matin": "Matin", "ouverture": "Avant l'ouverture", "point": "Verdicts de l'ouverture",
        "cloture": "Soir", "prep": "Prédictions préparées", "scan": "Brief de la semaine"}


def lis(chemin, defaut=None):
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


def nombre(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def iso_utc(texte):
    """Ramene une heure ISO (avec Z ou decalage) en ISO UTC ; None si illisible."""
    if not texte:
        return None
    try:
        d = datetime.datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def verdict(sens, gap):
    if gap is None or sens not in ("H", "B"):
        return None
    if abs(gap) < PLAT:
        return "plat"
    return "juste" if (gap > 0) == (sens == "H") else "faux"


def decoupe_raisonnement(texte):
    """Tire du champ raisonnement : les raisons, le « change si » et l'heure de publication."""
    texte = texte or ""
    tete = texte.split(" | ")[0]
    m = re.search(r"→[^.]*?\)\.\s*(.*)", tete, re.S)
    corps = (m.group(1) if m else "").strip()
    change = ""
    m = re.search(r"Changerait d'avis\s*:\s*(.*)", corps, re.S)
    if m:
        change = m.group(1).strip().rstrip(".")
        corps = corps[:m.start()].strip()
    quand = ""
    m = re.search(r"Call\s*:\s*(.+?)(?:\.\s*Cap\b|\s*\||$)", texte, re.S)
    if m:
        quand = re.sub(r"^publication\s+", "", m.group(1).strip().replace(" Paris", ""))
    releve = ""
    m = re.search(r"Spot\s+[\d.,]+\s*\$\s*\(([^)]{3,40})\)", texte)
    if m:
        releve = m.group(1).replace(" Paris", "").strip()
    return corps, change, quand, releve


def predictions(lignes, aujourd_hui):
    limite = (aujourd_hui - datetime.timedelta(days=JOURS_GARDES)).isoformat()
    veille = (aujourd_hui - datetime.timedelta(days=4)).isoformat()
    sortie = []
    for r in lignes:
        date = r.get("date_print") or ""
        if date < limite:
            continue
        officielle = r.get("sens") in ("Haussier", "Baissier")
        if officielle:
            sens = "H" if r["sens"] == "Haussier" else "B"
            proba = nombre(r.get("proba")) or nombre(r.get("avis_proba"))
        else:
            sens = r.get("avis_sens")
            proba = nombre(r.get("avis_proba"))
        if sens not in ("H", "B") or proba is None:
            continue
        gap = nombre(r.get("gap_pct"))
        if officielle:
            statut = {"Juste": "juste", "Eroné": "faux", "Erroné": "faux", "Plat": "plat",
                      "En attente": "attente"}.get(r.get("statut"))
        elif gap is not None:
            statut = verdict(sens, gap)
        else:
            statut = "attente" if r.get("statut") == "En attente" else None
        if statut is None:
            continue
        if statut == "attente" and date < veille:
            continue  # vieille ligne jamais mesuree : pas une prediction en jeu
        raisons, change, quand, cours_quand = decoupe_raisonnement(r.get("raisonnement"))
        if not officielle and proba < 55:
            raisons, change = "", ""  # avis faibles : une ligne suffit
        sortie.append({
            "id": r["_id"], "ticker": r.get("ticker"), "date": date, "seance": r.get("seance"),
            "officielle": officielle, "sens": sens, "proba": proba, "profil": r.get("profil"),
            "statut": statut, "gap": gap, "cours": nombre(r.get("spot")), "cible": nombre(r.get("cible")),
            "gap_typique": nombre(r.get("gap_typique")), "options": nombre(r.get("implicite")),
            "cap_md": nombre(r.get("cap_md")), "secteur": r.get("secteur") or "",
            "quand": quand, "raisons": raisons, "change_si": change, "cours_quand": cours_quand,
        })
    sortie.sort(key=lambda p: (p["date"], p["seance"] or "", not p["officielle"], -p["proba"], p["ticker"] or ""))
    return sortie


def score(lignes, banc):
    offs = [r for r in lignes if r.get("sens") in ("Haussier", "Baissier") and r.get("regle") == REGLE]
    tranchees, signes = [], []
    compte = {"juste": 0, "faux": 0, "plat": 0, "attente": 0}
    for r in sorted(offs, key=lambda r: (r.get("date_print") or "", r.get("ticker") or "")):
        st = {"Juste": "juste", "Eroné": "faux", "Erroné": "faux", "Plat": "plat",
              "En attente": "attente"}.get(r.get("statut"))
        if st is None:
            continue
        compte[st] += 1
        gap = nombre(r.get("gap_pct"))
        sens = "H" if r["sens"] == "Haussier" else "B"
        if st in ("juste", "faux"):
            if gap is not None:
                signes.append(gap if sens == "H" else -gap)
            tranchees.append({"ticker": r.get("ticker"), "date": r.get("date_print"), "sens": sens,
                              "proba": nombre(r.get("proba")), "gap": gap, "statut": st})
    n = compte["juste"] + compte["faux"]
    avis = {"juste": 0, "faux": 0, "plat": 0}
    for r in lignes:
        if r.get("sens") in ("Haussier", "Baissier") or r.get("regle") != REGLE:
            continue
        if (nombre(r.get("avis_proba")) or 0) < 55:
            continue
        v = verdict(r.get("avis_sens"), nombre(r.get("gap_pct")))
        if v:
            avis[v] += 1
    profils = []
    for p in ((banc or {}).get("correlation") or {}).get("profils") or []:
        profils.append({"profil": p.get("profil"), "justes": p.get("justes"),
                        "tranchees": p.get("tranchees"), "proba": p.get("proba")})
    return {
        "regle": REGLE, "objectif": OBJECTIF,
        "justes": compte["juste"], "faux": compte["faux"], "plats": compte["plat"],
        "en_attente": compte["attente"], "tranchees": n,
        "taux": round(100 * compte["juste"] / n, 1) if n else None,
        "gap_signe_moyen": round(sum(signes) / len(signes), 2) if signes else None,
        "liste": tranchees[::-1],
        "avis55": avis,
        "profils": profils,
        "banc_calcule_le": iso_utc((banc or {}).get("calcule_le")),
    }


def points(meta, existants):
    par_id = {p["id"]: p for p in existants if isinstance(p, dict) and p.get("id")}
    for nom, doc in meta.items():
        if not nom.startswith("fil_") or not isinstance(doc, dict):
            continue
        texte, date = (doc.get("texte") or "").strip(), doc.get("date")
        genre = doc.get("routine") or nom[4:]
        if not texte or not date:
            continue
        ident = "%s-%s" % (date, genre)
        par_id[ident] = {"id": ident, "type": genre, "nom": NOMS.get(genre, genre), "date": date,
                         "heure": iso_utc(doc.get("heure")), "texte": texte}
    liste = sorted(par_id.values(), key=lambda p: (p.get("heure") or p["date"]), reverse=True)
    return liste[:POINTS_GARDES]


def agenda(scan):
    """Decoupe le brief du dimanche en jours et rendez-vous."""
    if not isinstance(scan, dict) or not scan.get("texte"):
        return None
    annee = (scan.get("date") or "")[:4]
    lignes = scan["texte"].split("\n")
    jours, courant, titre = [], None, lignes[0].strip()
    for brut in lignes[1:]:
        ligne = brut.strip()
        if not ligne:
            continue
        m = re.match(r"^(%s)\b\s*(\d{1,2}/\d{1,2})?\s*[—-]?\s*(.*)$" % "|".join(JOURS), ligne)
        if m and not ligne.startswith("- "):
            date = None
            if m.group(2) and annee:
                j, mo = m.group(2).split("/")
                date = "%s-%02d-%02d" % (annee, int(mo), int(j))
            courant = {"jour": m.group(1).capitalize(), "date": date, "note": m.group(3).strip(), "items": []}
            jours.append(courant)
            continue
        if re.match(r"^[A-ZÉÈÀ' ]{8,}$", ligne):
            courant = None  # autre rubrique en capitales : hors agenda
            continue
        if courant is not None and ligne.startswith("- "):
            corps = ligne[2:]
            quand, sep, reste = corps.partition(" — ")
            if not sep:
                quand, reste = "", corps
            courant["items"].append({"quand": quand.strip(), "texte": reste.strip()})
    return {"titre": titre, "ecrit_le": iso_utc(scan.get("heure")), "jours": jours}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    export = sys.argv[1]
    site = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    sources = os.path.join(export, "appli")
    lignes = []
    for f in glob.glob(os.path.join(export, "journal", "*.json")):
        r = lis(f)
        if isinstance(r, dict):
            r["_id"] = os.path.basename(f)[:-5]
            lignes.append(r)
    meta = {}
    for f in glob.glob(os.path.join(export, "meta", "*.json")):
        meta[os.path.basename(f)[:-5]] = lis(f)
    publique = coffre.cle_publique(site)
    maintenant = datetime.datetime.now(datetime.timezone.utc)
    if lignes:
        coffre.ecris_donnee(site, "predictions", predictions(lignes, maintenant.date()), publique)
        coffre.ecris_donnee(site, "score", score(lignes, meta.get("banc")), publique)
    # L'archive des points et les alertes vivent en clair dans <export>/appli (la base privee),
    # jamais en clair dans le site : les scripts ne savent pas relire ce qu'ils ont chiffre.
    archive = points(meta, lis(os.path.join(sources, "points.json"), []))
    ecris(os.path.join(sources, "points.json"), archive)
    coffre.ecris_donnee(site, "points", archive, publique)
    ag = agenda(meta.get("fil_scan"))
    if ag:
        coffre.ecris_donnee(site, "agenda", ag, publique)
    coffre.ecris_donnee(site, "alertes", lis(os.path.join(sources, "alertes.json"), []), publique)
    coffre.ecris_donnee(site, "argent", lis(os.path.join(sources, "argent.json"), {}), publique)
    ecris(os.path.join(site, "data", "etat.json"), {"maj": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                   "chiffre": publique is not None})
    print("synchro : %d lignes lues, donnees %s dans %s" % (
        len(lignes), "chiffrees" if publique is not None else "EN CLAIR", os.path.normpath(os.path.join(site, "data"))))


if __name__ == "__main__":
    main()
