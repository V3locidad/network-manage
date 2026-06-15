#!/usr/bin/env bash
# Chiffre / déchiffre / affiche secret/switch_creds.yml avec Ansible Vault,
# via l'image du conteneur webui (qui embarque ansible-vault).
#
# Le mot de passe vault est lu depuis webui/.env (ANSIBLE_VAULT_PASSWORD) :
# définis-le LÀ d'abord.
#
# Usage :
#   ./secret/vault.sh encrypt   # chiffre le fichier en clair
#   ./secret/vault.sh view      # affiche le contenu déchiffré
#   ./secret/vault.sh decrypt   # remet le fichier en clair
#   ./secret/vault.sh rekey     # change le mot de passe vault
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cmd="${1:-}"
case "$cmd" in
  encrypt|decrypt|view|rekey) ;;
  *) echo "usage: $0 encrypt|decrypt|view|rekey"; exit 1 ;;
esac

# Charge ANSIBLE_VAULT_PASSWORD depuis webui/.env.
set -a; . "$ROOT/webui/.env"; set +a
if [ -z "${ANSIBLE_VAULT_PASSWORD:-}" ]; then
  echo "ERREUR : ANSIBLE_VAULT_PASSWORD n'est pas défini dans webui/.env"
  exit 1
fi

docker run --rm -e ANSIBLE_VAULT_PASSWORD="$ANSIBLE_VAULT_PASSWORD" \
  -v "$ROOT/secret:/secret" -v "$ROOT:/project:ro" \
  net-automation/webui:latest \
  ansible-vault "$cmd" \
    --vault-password-file /project/secret/vault_pass.sh \
    /secret/switch_creds.yml
