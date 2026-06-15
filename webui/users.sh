#!/usr/bin/env bash
# Gestion des comptes de l'interface web, exécutée DANS le conteneur webui
# (qui embarque Werkzeug et a accès à /backups).
#
# Exemples :
#   ./webui/users.sh list
#   ./webui/users.sh add julien            # mot de passe par défaut Switch2026!
#   ./webui/users.sh add tech1 'MonMdp123' # avec un mot de passe choisi
#   ./webui/users.sh reset julien          # repart sur le mot de passe par défaut
#   ./webui/users.sh del tech1
#
# Les comptes créés via add/reset DOIVENT changer leur mot de passe à la
# première connexion. Tant qu'aucun compte n'existe, l'interface reste en
# mode « mot de passe partagé » (WEBUI_PASSWORD).
set -euo pipefail
cd "$(dirname "$0")"
docker compose run --rm --no-deps -T webui \
  python /project/webui/manage_users.py "$@"
