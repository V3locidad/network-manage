#!/usr/bin/env bash
# Prise en main : prépare l'environnement Ansible du projet.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Création du venv Python"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installation d'Ansible"
pip install --quiet --upgrade pip ansible

echo "==> Installation des collections réseau"
ansible-galaxy collection install -r requirements.yml

if [ ! -f inventory/group_vars/all/vault.yml ]; then
  echo "==> Création du fichier de secrets depuis le modèle"
  cp inventory/group_vars/all/vault.example.yml inventory/group_vars/all/vault.yml
  echo "    ⚠  Édite inventory/group_vars/all/vault.yml puis chiffre-le :"
  echo "       ansible-vault encrypt inventory/group_vars/all/vault.yml"
fi

echo
echo "✅ Prêt. Étapes suivantes :"
echo "   1. source .venv/bin/activate"
echo "   2. Renseigne tes switchs dans inventory/hosts.yml"
echo "   3. Édite + chiffre inventory/group_vars/all/vault.yml"
echo "   4. Test sans risque : ansible-playbook playbooks/backup_config.yml --ask-vault-pass"
