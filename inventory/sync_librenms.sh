#!/usr/bin/env bash
# Re-génère inventory/hosts.yml depuis LibreNMS (auto-détection du vendor,
# noms en MAJUSCULES). À lancer quand le parc a changé dans LibreNMS.
#
# Les identifiants (LNMS_URL / LNMS_TOKEN) sont lus depuis webui/.env, où
# l'installeur les a enregistrés.
#
#   ./inventory/sync_librenms.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# shellcheck disable=SC1091
set -a; . "$ROOT/webui/.env"; set +a
if [ -z "${LNMS_URL:-}" ] || [ -z "${LNMS_TOKEN:-}" ]; then
  echo "ERREUR : LNMS_URL et/ou LNMS_TOKEN absents de webui/.env."
  echo "Ajoute-les puis relance, ou repasse par install.sh."
  exit 1
fi

docker run --rm --network host \
  -e LNMS_URL="$LNMS_URL" -e LNMS_TOKEN="$LNMS_TOKEN" \
  -v "$ROOT:/project" net-automation/webui:latest \
  python /project/inventory/from_librenms.py /project/inventory/hosts.yml

echo "➜ Inventaire mis à jour. L'interface le reflète immédiatement (relecture du fichier)."
