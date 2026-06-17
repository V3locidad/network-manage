#!/usr/bin/env python3
"""Client minimal pour la NOUVELLE API HPE Aruba Networking Central (GreenLake).

Auth en client_credentials -> access token, puis appels REST.
Aucune dépendance externe (urllib + json de la stdlib).

⚠️ Les identifiants NE sont PAS dans ce fichier (versionné) : ils viennent de
variables d'environnement (à mettre dans webui/.env, git-ignoré) :

  CENTRAL_TOKEN_URL        défaut: https://sso.common.cloud.hpe.com/as/token.oauth2
  CENTRAL_CLIENT_ID        client d'API personnel (Central)
  CENTRAL_CLIENT_SECRET    secret du client d'API
  CENTRAL_BASE_URL         URL de base régionale de l'API Central (EU West)
  CENTRAL_INVENTORY_PATH   défaut: /devices  (chemin de l'inventaire — à ajuster)

Usage :
  central.py token        teste l'authentification (vérifie qu'on obtient un token)
  central.py inventory    récupère et affiche l'inventaire des appareils Central
  central.py raw <chemin> GET brut sur <chemin> (pour explorer l'API)
"""
import json
import os
import sys
import urllib.parse
import urllib.request

TOKEN_URL = os.environ.get("CENTRAL_TOKEN_URL",
                           "https://sso.common.cloud.hpe.com/as/token.oauth2")
CLIENT_ID = os.environ.get("CENTRAL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CENTRAL_CLIENT_SECRET", "")
BASE_URL = os.environ.get("CENTRAL_BASE_URL", "").rstrip("/")
INVENTORY_PATH = os.environ.get("CENTRAL_INVENTORY_PATH", "/devices")


def get_token():
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["access_token"]


def api_get(path, token):
    req = urllib.request.Request(
        BASE_URL + path,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "token"
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("CENTRAL_CLIENT_ID / CENTRAL_CLIENT_SECRET manquants (webui/.env).")
    token = get_token()

    if cmd == "token":
        print("✅ Auth OK — access token obtenu (longueur %d)." % len(token))
        return
    if not BASE_URL:
        sys.exit("CENTRAL_BASE_URL manquant (URL régionale EU West de l'API).")
    if cmd == "inventory":
        print(json.dumps(api_get(INVENTORY_PATH, token), indent=2)[:6000])
        return
    if cmd == "raw" and len(sys.argv) > 2:
        print(json.dumps(api_get(sys.argv[2], token), indent=2)[:6000])
        return
    sys.exit("commande: token | inventory | raw <chemin>")


if __name__ == "__main__":
    main()
