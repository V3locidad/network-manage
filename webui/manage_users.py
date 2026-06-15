#!/usr/bin/env python3
"""Gestion des comptes de l'interface web (fichier /backups/users.json).

À lancer DANS le conteneur webui (il embarque Werkzeug) — voir users.sh.

Usage :
  manage_users.py list
  manage_users.py add   <login> [mot_de_passe_par_defaut]   # défaut: Switch2026!
  manage_users.py reset <login> [mot_de_passe_par_defaut]   # remet le défaut
  manage_users.py del   <login>

« add » et « reset » forcent le changement de mot de passe à la prochaine connexion.
"""
import json
import os
import sys

from werkzeug.security import generate_password_hash

USERS_FILE = os.environ.get("USERS_FILE", "/backups/users.json")
DEFAULT_PASSWORD = "Switch2026!"


def load():
    try:
        with open(USERS_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(users):
    with open(USERS_FILE, "w") as fh:
        json.dump(users, fh, ensure_ascii=False, indent=1)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    cmd = args[0]
    users = load()

    if cmd == "list":
        if not users:
            print("(aucun compte — mode mot de passe partagé)")
        for login, u in sorted(users.items()):
            flag = "  [mot de passe par défaut]" if u.get("must_change") else ""
            print(f"- {login}{flag}")
        return

    if cmd in ("add", "reset"):
        if len(args) < 2:
            print(f"usage: manage_users.py {cmd} <login> [mot_de_passe]")
            sys.exit(1)
        login = args[1]
        pwd = args[2] if len(args) > 2 else DEFAULT_PASSWORD
        users[login] = {"hash": generate_password_hash(pwd), "must_change": True}
        save(users)
        print(f"✅ {cmd} « {login} » — mot de passe par défaut : {pwd}")
        print("   (sera demandé de le changer à la première connexion)")
        return

    if cmd == "del":
        if len(args) < 2:
            print("usage: manage_users.py del <login>")
            sys.exit(1)
        if users.pop(args[1], None) is not None:
            save(users)
            print(f"🗑️  compte « {args[1]} » supprimé")
        else:
            print(f"compte « {args[1]} » introuvable")
        return

    print(f"commande inconnue : {cmd}")
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
