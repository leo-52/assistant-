"""Chiffrement des fichiers de donnees de l'appli.

Le fichier data/cle.json contient la cle PUBLIQUE (RSA-OAEP 3072, SHA-256) et la cle privee
chiffree par le mot de passe de leo (PBKDF2-SHA256 puis AES-256-GCM). Les scripts n'ont besoin
que de la cle publique : ils ne connaissent jamais le mot de passe et ne peuvent pas relire
ce qu'ils ont chiffre.

Enveloppe d'un fichier chiffre :
  {"chiffre": 1, "alg": "RSA-OAEP-256+A256GCM", "k": <cle AES enveloppee, base64>,
   "iv": <base64, 12 octets>, "c": <texte chiffre + etiquette GCM, base64>}
Format identique a WebCrypto : l'appli le dechiffre dans le navigateur.
"""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _b64url_entier(texte):
    brut = base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))
    return int.from_bytes(brut, "big")


def cle_publique(site):
    """Cle publique lue dans <site>/data/cle.json, ou None si l'appli n'est pas encore verrouillee."""
    chemin = os.path.join(site, "data", "cle.json")
    if not os.path.exists(chemin):
        return None
    with open(chemin, encoding="utf-8") as f:
        jwk = json.load(f)["publique"]
    if jwk.get("kty") != "RSA":
        raise ValueError("cle.json : cle publique RSA attendue")
    return rsa.RSAPublicNumbers(_b64url_entier(jwk["e"]), _b64url_entier(jwk["n"])).public_key()


def enveloppe(publique, objet):
    donnees = json.dumps(objet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    cle = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    c = AESGCM(cle).encrypt(iv, donnees, None)
    k = publique.encrypt(cle, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                           algorithm=hashes.SHA256(), label=None))
    b = lambda x: base64.b64encode(x).decode("ascii")
    return {"chiffre": 1, "alg": "RSA-OAEP-256+A256GCM", "k": b(k), "iv": b(iv), "c": b(c)}


def ecris_donnee(site, nom, objet, publique):
    """Ecrit <site>/data/<nom>.json, chiffre si une cle publique existe."""
    chemin = os.path.join(site, "data", nom + ".json")
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    sortie = enveloppe(publique, objet) if publique is not None else objet
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=None if publique is not None else 1)
        f.write("\n")
