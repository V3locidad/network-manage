#!/usr/bin/env python3
"""Client pour l'inventaire d'appareils HPE GreenLake (enregistrement Aruba Central).

Auth client_credentials (token tenant GreenLake), puis appels REST.
Sans dépendance externe (urllib + json).

⚠️ Les identifiants NE sont PAS dans ce fichier (versionné) : variables d'env
(à mettre dans webui/.env, git-ignoré) :

  CENTRAL_CUSTOMER_ID    platform_customer_id GreenLake (dans l'URL du token)
  CENTRAL_CLIENT_ID      client d'API GreenLake
  CENTRAL_CLIENT_SECRET  secret du client
  CENTRAL_BASE_URL       défaut: https://global.api.greenlake.hpe.com
  CENTRAL_TOKEN_URL      (optionnel) sinon construit depuis BASE + customer_id

Usage :
  central.py token                 teste l'authentification
  central.py inventory             liste les appareils enregistrés (série/MAC/modèle)
  central.py serials               n'affiche que les numéros de série enregistrés
  central.py register <SÉRIE> <MAC>   enregistre un switch (POST, ÉCRIT sur le compte)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("CENTRAL_BASE_URL",
                          "https://global.api.greenlake.hpe.com").rstrip("/")
CUSTOMER_ID = os.environ.get("CENTRAL_CUSTOMER_ID", "")
CLIENT_ID = os.environ.get("CENTRAL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CENTRAL_CLIENT_SECRET", "")
TOKEN_URL = os.environ.get("CENTRAL_TOKEN_URL") or (
    "%s/authorization/v2/oauth2/%s/token" % (BASE_URL, CUSTOMER_ID))
DEVICES_PATH = os.environ.get("CENTRAL_INVENTORY_PATH", "/devices/v1/devices")


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


def api_post(path, token, body):
    req = urllib.request.Request(
        BASE_URL + path, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode(errors="replace")
        return r.status, raw


def normalize_mac(mac):
    """Normalise une MAC (formats HP xxxxxx-xxxxxx, xx:xx:.., xxxx.xxxx.xxxx)
    en aa:bb:cc:dd:ee:ff minuscule. Renvoie '' si pas 12 hex."""
    hexd = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(hexd) != 12:
        return ""
    hexd = hexd.lower()
    return ":".join(hexd[i:i + 2] for i in range(0, 12, 2))


def register_device(token, serial, mac):
    """POST /devices/v1/devices — enregistre un switch réseau.
    Renvoie (ok: bool, message: str)."""
    nmac = normalize_mac(mac)
    if not serial or serial == "?":
        return False, "numéro de série manquant"
    if not nmac:
        return False, "MAC invalide ou manquante (%r)" % mac
    body = {"network": [{"serialNumber": serial, "macAddress": nmac}]}
    try:
        status, raw = api_post(DEVICES_PATH, token, body)
        return True, "HTTP %s %s" % (status, raw[:300])
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        return False, "HTTP %s %s" % (e.code, detail)
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def get_devices(token):
    """Tous les appareils enregistrés (pagination offset/limit)."""
    out, offset, limit = [], 0, 50
    while True:
        sep = "&" if "?" in DEVICES_PATH else "?"
        page = api_get("%s%slimit=%d&offset=%d" % (DEVICES_PATH, sep, limit, offset), token)
        items = page.get("items") if isinstance(page, dict) else (page or [])
        out.extend(items)
        total = page.get("total", len(out)) if isinstance(page, dict) else len(out)
        offset += limit
        if offset >= total or not items:
            break
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "token"
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("CENTRAL_CLIENT_ID / CENTRAL_CLIENT_SECRET manquants (webui/.env).")
    if not CUSTOMER_ID and "CENTRAL_TOKEN_URL" not in os.environ:
        sys.exit("CENTRAL_CUSTOMER_ID manquant (webui/.env).")

    if cmd == "register":
        if len(sys.argv) < 4:
            sys.exit("usage: central.py register <SÉRIE> <MAC>")
        token = get_token()
        ok, msg = register_device(token, sys.argv[2].strip(), sys.argv[3].strip())
        print(("✅ " if ok else "❌ ") + msg)
        sys.exit(0 if ok else 1)

    token = get_token()

    if cmd == "token":
        print("✅ Auth OK — access token obtenu (longueur %d)." % len(token))
        return
    devices = get_devices(token)
    if cmd == "serials":
        for d in devices:
            print(d.get("serialNumber", ""))
        return
    if cmd == "inventory":
        print("Appareils enregistrés (GreenLake) : %d" % len(devices))
        for d in devices:
            print("  - %-14s %-8s %-18s %s" % (
                d.get("serialNumber", "?"), d.get("model", ""),
                d.get("macAddress", ""), d.get("deviceType", "")))
        return
    sys.exit("commande: token | inventory | serials | register")


if __name__ == "__main__":
    main()
