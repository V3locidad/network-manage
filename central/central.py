#!/usr/bin/env python3
"""Client pour l'inventaire d'appareils HPE GreenLake (enregistrement Aruba Central).

Auth client_credentials (token tenant GreenLake), puis appels REST.
Sans dépendance externe (urllib + json).

⚠️ Les identifiants NE sont PAS dans ce fichier (versionné) : variables d'env
(à mettre dans webui/.env, git-ignoré) :

  CENTRAL_CLIENT_ID      client d'API GreenLake          (OBLIGATOIRE)
  CENTRAL_CLIENT_SECRET  secret du client                (OBLIGATOIRE)
  CENTRAL_CUSTOMER_ID    platform_customer_id GreenLake  (OPTIONNEL : découvert
                         automatiquement via l'endpoint SSO si absent)
  CENTRAL_BASE_URL       défaut: https://global.api.greenlake.hpe.com
  CENTRAL_TOKEN_URL      (optionnel) force l'URL du token tenant
  CENTRAL_SSO_TOKEN_URL  défaut: https://sso.common.cloud.hpe.com/as/token.oauth2

Usage :
  central.py token                 teste l'authentification
  central.py customer              affiche le platform_customer_id (auto-découvert)
  central.py inventory             liste les appareils enregistrés (série/MAC/modèle)
  central.py serials               n'affiche que les numéros de série enregistrés
  central.py register <SÉRIE> <MAC>   enregistre un switch (POST + poll du résultat)
  central.py status <transactionId>   statut d'une opération async (diagnostic)
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("CENTRAL_BASE_URL",
                          "https://global.api.greenlake.hpe.com").rstrip("/")
CUSTOMER_ID = os.environ.get("CENTRAL_CUSTOMER_ID", "")
CLIENT_ID = os.environ.get("CENTRAL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CENTRAL_CLIENT_SECRET", "")
# Endpoint SSO global HPE : accepte client_credentials SANS connaître le
# customer_id (il est encodé DANS le token). Sert à découvrir le customer_id.
SSO_TOKEN_URL = os.environ.get(
    "CENTRAL_SSO_TOKEN_URL", "https://sso.common.cloud.hpe.com/as/token.oauth2")
DEVICES_PATH = os.environ.get("CENTRAL_INVENTORY_PATH", "/devices/v1/devices")


def tenant_token_url(customer_id):
    return "%s/authorization/v2/oauth2/%s/token" % (BASE_URL, customer_id)


def _post_token(url):
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["access_token"]


def jwt_claims(token):
    """Décode (sans vérifier la signature) les claims d'un JWT."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # padding base64url
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001
        return {}


def discover_customer_id():
    """Découvre le platform_customer_id via l'endpoint SSO global (le client
    n'a PAS besoin de le connaître à l'avance)."""
    return jwt_claims(_post_token(SSO_TOKEN_URL)).get("platform_customer_id", "")


def get_token():
    """Renvoie un access token GreenLake.
    - customer_id connu (env) ou CENTRAL_TOKEN_URL forcé -> auth directe (validée).
    - sinon -> découverte du customer_id via SSO, puis auth sur l'URL tenant."""
    if os.environ.get("CENTRAL_TOKEN_URL"):
        return _post_token(os.environ["CENTRAL_TOKEN_URL"])
    if CUSTOMER_ID:
        return _post_token(tenant_token_url(CUSTOMER_ID))
    # Pas de customer_id fourni : token SSO -> on en extrait le customer_id.
    sso_token = _post_token(SSO_TOKEN_URL)
    cust = jwt_claims(sso_token).get("platform_customer_id", "")
    if not cust:
        return sso_token  # repli : on tente l'API avec le token SSO.
    return _post_token(tenant_token_url(cust))


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


ASYNC_OP_PATH = "/devices/v1/async-operations"
_DONE = ("OK", "SUCCEEDED", "SUCCESS", "COMPLETE", "COMPLETED")
_FAILED = ("FAILED", "ERROR", "CANCELLED", "REJECTED")


def get_async_op(token, op_id):
    return api_get("%s/%s" % (ASYNC_OP_PATH, op_id), token)


def poll_async(token, op_id, attempts=6, delay=3):
    """Interroge /devices/v1/async-operations/{id} jusqu'à complétion.
    Renvoie (terminé: bool, op: dict|None)."""
    op = None
    for i in range(attempts):
        try:
            op = get_async_op(token, op_id)
        except Exception:  # noqa: BLE001
            return False, op
        st = str(op.get("status", op.get("state", ""))).upper()
        if st in _DONE or st in _FAILED:
            return True, op
        if i < attempts - 1:
            time.sleep(delay)
    return False, op


def normalize_mac(mac):
    """Normalise une MAC (formats HP xxxxxx-xxxxxx, xx:xx:.., xxxx.xxxx.xxxx)
    en aa:bb:cc:dd:ee:ff minuscule. Renvoie '' si pas 12 hex."""
    hexd = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(hexd) != 12:
        return ""
    hexd = hexd.lower()
    return ":".join(hexd[i:i + 2] for i in range(0, 12, 2))


def register_device(token, serial, mac):
    """POST /devices/v1/devices puis poll de l'opération async pour connaître le
    VRAI résultat (le 202 ne garantit rien). Renvoie (ok: bool, message: str)."""
    nmac = normalize_mac(mac)
    if not serial or serial == "?":
        return False, "numéro de série manquant"
    if not nmac:
        return False, "MAC invalide ou manquante (%r)" % mac
    # L'API exige les 3 familles présentes ; celles qu'on n'ajoute pas = [].
    body = {"compute": [], "storage": [],
            "network": [{"serialNumber": serial, "macAddress": nmac}]}
    try:
        _status, raw = api_post(DEVICES_PATH, token, body)
    except urllib.error.HTTPError as e:
        return False, "HTTP %s %s" % (e.code, e.read().decode(errors="replace")[:800])
    except Exception as e:  # noqa: BLE001
        return False, str(e)

    try:
        op_id = (json.loads(raw) or {}).get("transactionId", "")
    except Exception:  # noqa: BLE001
        op_id = ""
    if not op_id:
        return True, "accepté mais transactionId introuvable : %s" % raw[:300]

    done, op = poll_async(token, op_id)
    if op is None:
        return True, "accepté (transactionId %s) — statut non lisible" % op_id
    st = str(op.get("status", op.get("state", "?")))
    summary = json.dumps(op, ensure_ascii=False)[:600]
    if not done:
        return True, "en cours (transactionId %s, statut %s) — recharge plus tard" % (op_id, st)
    ok = st.upper() in _DONE
    return ok, "statut %s — %s" % (st, summary)


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
    # CENTRAL_CUSTOMER_ID est OPTIONNEL : s'il manque, on le découvre via SSO.

    if cmd == "customer":
        # Affiche le platform_customer_id (utile à l'install pour le persister).
        cust = CUSTOMER_ID or discover_customer_id()
        if not cust:
            sys.exit("Impossible de découvrir le customer_id (auth échouée ?).")
        print(cust)
        return

    if cmd == "register":
        if len(sys.argv) < 4:
            sys.exit("usage: central.py register <SÉRIE> <MAC>")
        token = get_token()
        ok, msg = register_device(token, sys.argv[2].strip(), sys.argv[3].strip())
        print(("✅ " if ok else "❌ ") + msg)
        sys.exit(0 if ok else 1)

    if cmd == "status":
        if len(sys.argv) < 3:
            sys.exit("usage: central.py status <transactionId>")
        token = get_token()
        print(json.dumps(get_async_op(token, sys.argv[2].strip()),
                         ensure_ascii=False, indent=2))
        return

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
    sys.exit("commande: token | customer | inventory | serials | register | status")


if __name__ == "__main__":
    main()
