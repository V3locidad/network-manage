#!/usr/bin/env bash
# ============================================================================
# Amorçage d'un NOUVEAU site : crée les fichiers locaux (non versionnés) à
# partir des modèles, génère les secrets, prépare les dossiers.
# À lancer une fois après avoir cloné le dépôt sur le serveur/LXC du site.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Amorçage du site dans : $(pwd)"

# 1. Inventaire
if [ ! -f inventory/hosts.yml ]; then
  cp inventory/hosts.example.yml inventory/hosts.yml
  echo "  [créé] inventory/hosts.yml          → édite-le avec tes switchs"
else
  echo "  [ok]   inventory/hosts.yml existe déjà"
fi

# 2. Identifiants des switchs (interface web)
mkdir -p secret
if [ ! -f secret/switch_creds.yml ]; then
  cp secret/switch_creds.example.yml secret/switch_creds.yml
  chmod 600 secret/switch_creds.yml
  echo "  [créé] secret/switch_creds.yml      → mets ansible_user/ansible_password"
else
  echo "  [ok]   secret/switch_creds.yml existe déjà"
fi

# 3. Config interface web maison
if [ ! -f webui/.env ]; then
  cp webui/.env.example webui/.env
  rnd="$(head -c32 /dev/urandom | base64)"
  sed -i "s|change_me_random|${rnd}|" webui/.env 2>/dev/null || \
    sed -i '' "s|change_me_random|${rnd}|" webui/.env
  echo "  [créé] webui/.env                   → choisis WEBUI_PASSWORD"
else
  echo "  [ok]   webui/.env existe déjà"
fi

# 4. Config standard du site (NTP/SNMP/logging/sécurité ports)
if [ ! -f inventory/group_vars/all/site.yml ]; then
  cp inventory/group_vars/all/site.example.yml inventory/group_vars/all/site.yml
  echo "  [créé] inventory/group_vars/all/site.yml → renseigne NTP/SNMP/etc."
else
  echo "  [ok]   inventory/group_vars/all/site.yml existe déjà"
fi

# 5. Dossier des sauvegardes (persistant, accessible au conteneur)
mkdir -p backups
chmod 777 backups
echo "  [ok]   backups/ prêt"

cat <<'EOF'

✅ Amorçage terminé. Étapes restantes :
   1. Édite  inventory/hosts.yml          (les switchs du site)
   2. Édite  secret/switch_creds.yml      (compte d'accès aux switchs)
   3. Édite  webui/.env                   (mot de passe de l'interface)
   4. Lance  cd webui && docker compose up -d --build
   5. Accès  http://<ip-du-serveur>:8080
EOF
