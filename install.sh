#!/usr/bin/env bash
# ============================================================================
#  Installeur tout-en-un de net-automation, pour un LXC/VM Debian vierge.
#
#  À lancer en root :   bash install.sh
#  (ou directement :    curl -fsSL <raw>/install.sh | bash )
#
#  Il fait TOUT :
#   - installe Docker + dépendances
#   - récupère le projet dans /opt/net-automation
#   - pose les questions (réseaux pare-feu, LibreNMS, compte admin, switchs…)
#   - génère l'inventaire (auto-détection cisco/aruba/procurve via LibreNMS)
#   - construit et démarre toute la stack (webui, terminal, reverse proxy HTTPS)
#   - crée le premier compte et (optionnel) applique le pare-feu
#
#  Prérequis hôte Proxmox : le conteneur doit être PRIVILÉGIÉ + features
#  nesting=1 (sinon Docker ne démarre pas dans le LXC).
# ============================================================================
set -euo pipefail

# Dans un LXC, le builder BuildKit échoue souvent (mount overlayfs refusé) :
# on force le builder classique, qui fonctionne en conteneur.
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0

REPO_URL="${REPO_URL:-https://github.com/V3locidad/network-manage.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/net-automation}"
IMAGE="net-automation/webui:latest"

c_blue='\033[1;34m'; c_grn='\033[1;32m'; c_yel='\033[1;33m'; c_red='\033[1;31m'; c_off='\033[0m'
say()  { echo -e "${c_blue}==>${c_off} $*"; }
ok()   { echo -e "${c_grn}  ✅ $*${c_off}"; }
warn() { echo -e "${c_yel}  ⚠ $*${c_off}"; }
err()  { echo -e "${c_red}  ✗ $*${c_off}" >&2; }
ask()  { # ask "Question" "defaut" -> renvoie la réponse dans REPLY_VAL
  local q="$1" def="${2:-}" ans
  if [ -n "$def" ]; then read -rp "   $q [$def] : " ans; else read -rp "   $q : " ans; fi
  REPLY_VAL="${ans:-$def}"
}
ask_secret() { # ask_secret "Question" -> REPLY_VAL (saisie masquée)
  local q="$1" ans; read -rsp "   $q : " ans; echo; REPLY_VAL="$ans"
}
yesno() { # yesno "Question" "o"|"n" -> 0 si oui
  local q="$1" def="${2:-n}" ans
  read -rp "   $q $( [ "$def" = o ] && echo '[O/n]' || echo '[o/N]' ) : " ans
  ans="${ans:-$def}"; [[ "$ans" =~ ^[oOyY] ]]
}

# Met à jour/ajoute KEY=VALUE dans un fichier .env (sans souci d'échappement sed).
set_kv() {
  local f="$1" k="$2" v="$3"
  touch "$f"
  grep -v "^${k}=" "$f" > "${f}.tmp" 2>/dev/null || true
  printf '%s=%s\n' "$k" "$v" >> "${f}.tmp"
  mv "${f}.tmp" "$f"
}

configure_vfs() {
  # vfs n'utilise aucun mount overlay -> contourne le refus overlayfs en LXC.
  mkdir -p /etc/docker
  cat > /etc/docker/daemon.json <<'JSON'
{
  "storage-driver": "vfs",
  "features": { "containerd-snapshotter": false }
}
JSON
  systemctl restart docker
  sleep 4
}

preflight_containers() {
  # Vérifie que Docker peut RÉELLEMENT lancer un conteneur dans ce LXC.
  say "Vérification du support des conteneurs (LXC)"
  if docker run --rm hello-world >/dev/null 2>&1; then ok "Conteneurs OK"; return; fi
  warn "Échec au premier essai — bascule du stockage Docker en 'vfs'…"
  configure_vfs
  if docker run --rm hello-world >/dev/null 2>&1; then ok "Conteneurs OK (stockage vfs)"; return; fi
  err "Docker ne peut pas démarrer de conteneur dans ce LXC."
  echo
  echo "   Cause : le conteneur LXC n'a pas 'nesting' activé (montage /proc refusé)."
  echo "   Sur l'HÔTE Proxmox, exécute :"
  echo "       pct set <CTID> --features nesting=1,keyctl=1"
  echo "       pct reboot <CTID>"
  echo "   puis relance ce script."
  exit 1
}

[ "$(id -u)" -eq 0 ] || { err "Lance ce script en root."; exit 1; }

echo
echo "  ┌──────────────────────────────────────────────┐"
echo "  │   Installation de net-automation (switchs)   │"
echo "  └──────────────────────────────────────────────┘"
echo

# ---------------------------------------------------------------------------
# 1. Dépendances système + Docker
# ---------------------------------------------------------------------------
say "Installation des dépendances système"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl git openssl ca-certificates >/dev/null
ok "curl, git, openssl, ca-certificates"

if ! command -v docker >/dev/null 2>&1; then
  say "Installation de Docker"
  curl -fsSL https://get.docker.com | sh >/dev/null
  systemctl enable --now docker >/dev/null 2>&1 || true
  ok "Docker installé"
else
  ok "Docker déjà présent"
fi
docker compose version >/dev/null 2>&1 || { err "Le plugin 'docker compose' manque."; exit 1; }

# En LXC, BuildKit casse souvent (réseau/overlay). On force le builder classique
# pour TOUS les shells de la machine -> les rebuilds manuels marchent aussi.
cat > /etc/profile.d/net-automation-docker.sh <<'EOF'
# net-automation : builder Docker classique (BuildKit échoue en LXC)
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0
EOF

# Vérifie tout de suite que les conteneurs démarrent (sinon inutile d'aller plus loin).
preflight_containers

# ---------------------------------------------------------------------------
# 2. Récupération du code
# ---------------------------------------------------------------------------
if [ -f "$(dirname "$0")/webui/app.py" ]; then
  SRC="$(cd "$(dirname "$0")" && pwd)"
  if [ "$SRC" != "$INSTALL_DIR" ]; then
    say "Copie du projet vers $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp -a "$SRC/." "$INSTALL_DIR/"
  fi
else
  if [ -d "$INSTALL_DIR/.git" ]; then
    say "Mise à jour du dépôt dans $INSTALL_DIR"; git -C "$INSTALL_DIR" pull --ff-only || true
  else
    say "Clonage du dépôt dans $INSTALL_DIR"; git clone "$REPO_URL" "$INSTALL_DIR"
  fi
fi
cd "$INSTALL_DIR"
ok "Projet dans $INSTALL_DIR"

# Réseau Docker partagé
docker network inspect netauto >/dev/null 2>&1 || docker network create netauto >/dev/null
ok "Réseau Docker 'netauto'"

# Fichiers locaux depuis les modèles (inventaire, .env, secrets, backups…)
say "Préparation des fichiers de site"
bash setup-site.sh >/dev/null
mkdir -p backups && chmod 777 backups
ok "Fichiers de site initialisés"

# IP détectées du LXC (pour proposer des valeurs par défaut)
DETECTED_IPS="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]' | paste -sd' ' -)"
FIRST_IP="$(echo "$DETECTED_IPS" | awk '{print $1}')"

# ---------------------------------------------------------------------------
# 3. Identifiants de connexion aux switchs
# ---------------------------------------------------------------------------
echo; say "Compte d'accès aux switchs (SSH) — commun à tout le parc"
ask "Nom d'utilisateur switch" "manager"; SW_USER="$REPLY_VAL"
ask_secret "Mot de passe switch";        SW_PASS="$REPLY_VAL"

# Mot de passe « enable » Cisco (nécessaire UNIQUEMENT pour configurer des
# Cisco : VLAN/port). Vide si pas de Cisco, ou si l'enable = le mot de passe
# ci-dessus. La lecture (inventaire/firmware) n'en a pas besoin.
SW_ENABLE=""
if yesno "As-tu des switchs Cisco à configurer (VLAN/port) ?" n; then
  ask_secret "Mot de passe enable Cisco (vide si identique au mot de passe ci-dessus)"
  SW_ENABLE="$REPLY_VAL"
fi

{
  echo "---"
  echo "ansible_user: \"${SW_USER}\""
  echo "ansible_password: \"${SW_PASS}\""
  [ -n "$SW_ENABLE" ] && echo "cisco_enable_password: \"${SW_ENABLE}\""
  cat <<'NOTE'

# --- Identifiants PAR CONSTRUCTEUR (optionnel) ------------------------------
# À renseigner SEULEMENT si un type de switch utilise un compte DIFFÉRENT du
# compte commun ci-dessus (sinon laisse commenté : le compte commun s'applique).
#   vault_cisco_user: ""        # Cisco IOS / NX-OS
#   vault_cisco_pass: ""
#   vault_aruba_cx_user: ""     # Aruba CX (SSH)
#   vault_aruba_cx_pass: ""
# (ProCurve/Aruba OS-Switch utilisent le compte commun.)
NOTE
} > secret/switch_creds.yml
chmod 600 secret/switch_creds.yml
ok "secret/switch_creds.yml créé"

# ---------------------------------------------------------------------------
# 4. Inventaire : LibreNMS (auto) ou manuel
# ---------------------------------------------------------------------------
echo; say "Inventaire des switchs"
USE_LNMS=no
if yesno "Générer l'inventaire automatiquement depuis LibreNMS ?" o; then
  ask "URL de LibreNMS (ex: http://${FIRST_IP%.*}.250)" ""; LNMS_URL="$REPLY_VAL"
  ask_secret "Jeton API LibreNMS"; LNMS_TOKEN="$REPLY_VAL"
  # Persistés (hors Git) pour pouvoir re-synchroniser plus tard sans réinstaller.
  set_kv webui/.env LNMS_URL "$LNMS_URL"
  set_kv webui/.env LNMS_TOKEN "$LNMS_TOKEN"
  USE_LNMS=yes
fi

# ---------------------------------------------------------------------------
# 5. Réseaux pour le pare-feu
# ---------------------------------------------------------------------------
echo; say "Pare-feu : qui a le droit d'accéder à l'interface ?"
ask "Réseaux/IP admin autorisés (séparés par un espace)" "${FIRST_IP}/32"; ADMIN_NETS="$REPLY_VAL"
ask "Réseau de management des switchs (TFTP firmware)" "192.168.0.0/24"; SWITCH_NET="$REPLY_VAL"
cat > security/firewall.conf <<EOF
# Généré par install.sh — réseaux autorisés (spécifique au site, hors Git).
ADMIN_NETS="${ADMIN_NETS}"
SWITCH_NET="${SWITCH_NET}"
RESTRICT_SSH=false
EOF
ok "security/firewall.conf écrit"

# ---------------------------------------------------------------------------
# 6. Réglages de l'interface (.env) + serveur TFTP
# ---------------------------------------------------------------------------
ask "IP de ce serveur sur le réseau des switchs (serveur TFTP firmware)" "$FIRST_IP"; TFTP_IP="$REPLY_VAL"
set_kv webui/.env TFTP_SERVER "$TFTP_IP"
set_kv webui/.env WEBUI_PASSWORD "$(head -c12 /dev/urandom | base64 | tr -d '/+=')"
grep -q '^WEBUI_SECRET=' webui/.env || set_kv webui/.env WEBUI_SECRET "$(head -c32 /dev/urandom | base64)"

# Chiffrement Vault des identifiants switchs (optionnel mais recommandé)
echo; if yesno "Chiffrer les identifiants switchs avec Ansible Vault ?" o; then
  VAULT_PW="$(head -c18 /dev/urandom | base64 | tr -d '/+=')"
  set_kv webui/.env ANSIBLE_VAULT_PASSWORD "$VAULT_PW"
  ENCRYPT_VAULT=yes
  ok "Mot de passe Vault généré (stocké dans webui/.env)"
else
  ENCRYPT_VAULT=no
fi

# ---------------------------------------------------------------------------
# 6bis. Aruba Central / HPE GreenLake (optionnel)
# ---------------------------------------------------------------------------
echo; say "Aruba Central / HPE GreenLake (vérifier/enregistrer les switchs Aruba)"
USE_CENTRAL=no
if yesno "Utiliser Aruba Central / HPE GreenLake ?" n; then
  echo "  Dans HPE GreenLake : Manage Workspace > API > crée des identifiants"
  echo "  (Client Credentials). Récupère le Client ID et le Client Secret."
  echo "  Le customer_id (Workspace ID) sera découvert automatiquement, pas besoin"
  echo "  de le saisir."
  ask "Client ID GreenLake" ""; CENTRAL_CLIENT_ID="$REPLY_VAL"
  ask_secret "Client Secret GreenLake"; CENTRAL_CLIENT_SECRET="$REPLY_VAL"
  set_kv webui/.env CENTRAL_CLIENT_ID "$CENTRAL_CLIENT_ID"
  set_kv webui/.env CENTRAL_CLIENT_SECRET "$CENTRAL_CLIENT_SECRET"
  # Tag par défaut (optionnel) appliqué à chaque switch enregistré.
  # Convention courante : le tag = le nom du site (ex. « Kastler »), sans valeur.
  if yesno "Appliquer un tag par défaut aux switchs enregistrés ?" n; then
    ask "Nom du tag (ex. nom du site : Kastler)" ""; CENTRAL_TAG_KEY="$REPLY_VAL"
    ask "Valeur du tag (laisser vide pour un tag sans valeur)" ""; CENTRAL_TAG_VALUE="$REPLY_VAL"
    set_kv webui/.env CENTRAL_TAG_KEY "$CENTRAL_TAG_KEY"
    set_kv webui/.env CENTRAL_TAG_VALUE "$CENTRAL_TAG_VALUE"
  fi
  USE_CENTRAL=yes
fi

# ---------------------------------------------------------------------------
# 7. Certificat TLS (HTTPS par IP) + mot de passe du terminal
# ---------------------------------------------------------------------------
echo; say "HTTPS / reverse proxy"
ask "IP(s) par lesquelles tu accèderas à l'interface" "$DETECTED_IPS"; TLS_IPS="$REPLY_VAL"
bash proxy/gencert.sh $TLS_IPS >/dev/null
ok "Certificat TLS généré (proxy/certs/)"
# Le terminal WebSSH est protégé par le même login que l'interface (SSO via
# forward_auth) : aucun mot de passe supplémentaire à définir.

# ---------------------------------------------------------------------------
# 8. Construction des images
# ---------------------------------------------------------------------------
echo; say "Construction des images Docker (peut prendre quelques minutes)"
docker compose -f webui/docker-compose.yml build
ok "Image webui construite"

# Inventaire LibreNMS (nécessite l'image webui pour python + accès réseau)
if [ "$USE_LNMS" = yes ]; then
  say "Génération de l'inventaire depuis LibreNMS"
  if docker run --rm --network host \
       -e LNMS_URL="$LNMS_URL" -e LNMS_TOKEN="$LNMS_TOKEN" \
       -v "$INSTALL_DIR:/project" "$IMAGE" \
       python /project/inventory/from_librenms.py /project/inventory/hosts.yml; then
    ok "Inventaire généré (auto-détection cisco/aruba/procurve)"
  else
    warn "Échec LibreNMS — inventaire à compléter à la main (inventory/hosts.yml)"
  fi
else
  warn "Inventaire à compléter à la main : inventory/hosts.yml"
fi

# Aruba Central : découverte du customer_id + test d'auth (après le build)
if [ "$USE_CENTRAL" = yes ]; then
  say "Aruba Central : découverte du customer_id et test d'authentification"
  CENTRAL_CUSTOMER_ID="$(docker run --rm --network host \
       -e CENTRAL_CLIENT_ID="$CENTRAL_CLIENT_ID" \
       -e CENTRAL_CLIENT_SECRET="$CENTRAL_CLIENT_SECRET" \
       -v "$INSTALL_DIR:/project" -w /project "$IMAGE" \
       python central/central.py customer 2>/dev/null | tr -d '\r')"
  if [ -n "$CENTRAL_CUSTOMER_ID" ]; then
    set_kv webui/.env CENTRAL_CUSTOMER_ID "$CENTRAL_CUSTOMER_ID"
    ok "Aruba Central OK — customer_id découvert : $CENTRAL_CUSTOMER_ID"
  else
    warn "Auth Aruba Central échouée — vérifie Client ID/Secret (page « Aruba Central » dans l'UI)"
  fi
fi

# Chiffrement Vault effectif (après build, car ça utilise l'image)
if [ "${ENCRYPT_VAULT}" = yes ]; then
  say "Chiffrement de secret/switch_creds.yml"
  if bash secret/vault.sh encrypt >/dev/null 2>&1; then
    ok "Identifiants switchs chiffrés (Ansible Vault)"
  else
    warn "Chiffrement Vault échoué — fichier laissé en clair"
  fi
fi

# ---------------------------------------------------------------------------
# 9. Premier compte administrateur de l'interface
# ---------------------------------------------------------------------------
echo; say "Création du premier compte de l'interface web"
ask "Identifiant du compte admin" "admin"; ADM_LOGIN="$REPLY_VAL"
ask_secret "Mot de passe du compte admin"; ADM_PASS="$REPLY_VAL"
ADM_HASH="$(docker run --rm "$IMAGE" python -c \
  'import sys; from werkzeug.security import generate_password_hash as g; print(g(sys.argv[1]))' \
  "$ADM_PASS")"
cat > backups/users.json <<EOF
{
 "${ADM_LOGIN}": { "hash": "${ADM_HASH}", "must_change": false }
}
EOF
ok "Compte « ${ADM_LOGIN} » créé"

# ---------------------------------------------------------------------------
# 10. Démarrage de toute la stack
# ---------------------------------------------------------------------------
echo; say "Démarrage des services"
docker compose -f webui/docker-compose.yml  up -d >/dev/null
docker compose -f webssh/docker-compose.yml up -d --build >/dev/null
docker compose -f proxy/docker-compose.yml  up -d >/dev/null
( cd firmware && docker compose up -d --build >/dev/null 2>&1 ) || warn "Service TFTP firmware non démarré (optionnel)"
ok "webui, terminal et reverse proxy HTTPS démarrés"

# ---------------------------------------------------------------------------
# 11. Pare-feu (opt-in, car risque de coupure)
# ---------------------------------------------------------------------------
echo; say "Pare-feu"
warn "Cela restreindra l'accès aux réseaux : ${ADMIN_NETS}"
if yesno "Appliquer le pare-feu maintenant ?" n; then
  bash security/firewall.sh || warn "Erreur lors de l'application du pare-feu"
  echo
  warn "TESTE TOUT DE SUITE que tu accèdes encore à l'interface."
  if yesno "L'accès fonctionne toujours — rendre le pare-feu persistant ?" n; then
    apt-get install -y -qq iptables-persistent >/dev/null && netfilter-persistent save >/dev/null
    ok "Pare-feu persistant au reboot"
  else
    warn "Pare-feu NON persistant : un reboot le réinitialisera (filet de sécurité)."
  fi
else
  warn "Pare-feu non appliqué. Plus tard : bash security/firewall.sh"
fi

# ---------------------------------------------------------------------------
# Récapitulatif
# ---------------------------------------------------------------------------
ACCESS_IP="$(echo "$TLS_IPS" | awk '{print $1}')"
echo
echo -e "${c_grn}┌──────────────────────────────────────────────┐${c_off}"
echo -e "${c_grn}│              Installation terminée           │${c_off}"
echo -e "${c_grn}└──────────────────────────────────────────────┘${c_off}"
echo
echo "  Interface web :  https://${ACCESS_IP}     (compte : ${ADM_LOGIN})"
echo "  Terminal web  :  https://${ACCESS_IP}:8443  (même login que l'interface)"
echo
echo "  Le certificat est auto-signé : accepte l'avertissement du navigateur."
[ "$USE_LNMS" = yes ] || echo "  ➜ Complète tes switchs dans : ${INSTALL_DIR}/inventory/hosts.yml"
echo "  Gestion des comptes :  ./webui/users.sh add <login>"
echo
