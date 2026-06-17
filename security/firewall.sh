#!/usr/bin/env bash
# ============================================================================
# Pare-feu du LXC net-automation.
# - Interface web (443) + terminal (8443) : seulement depuis les postes admin.
# - TFTP firmware (69/udp) : seulement depuis le réseau des switchs.
#
# ⚠️ ÉDITE ADMIN_NETS CI-DESSOUS AVANT DE LANCER (sinon tu te coupes l'accès).
#    Recovery toujours possible via la console Proxmox : pct enter <CTID>
# ============================================================================
set -euo pipefail

# ====== CONFIGURATION =======================================================
# Les valeurs réelles sont lues depuis security/firewall.conf (généré par
# install.sh, hors dépôt Git). Les valeurs ci-dessous ne servent que de
# repli si firewall.conf est absent — ÉDITE-LES sinon tu te coupes l'accès.
ADMIN_NETS=(
  "10.0.0.240/32"   # <-- REMPLACE par ton/tes poste(s) admin
  "10.8.0.0/24"     # <-- REMPLACE par le subnet de ton VPN
)
SWITCH_NET="10.0.0.0/24"   # <-- REMPLACE par le réseau de management des switchs (TFTP)
RESTRICT_SSH=false             # true = limiter aussi le SSH du LXC aux ADMIN_NETS

CONF="$(dirname "$0")/firewall.conf"
if [ -f "$CONF" ]; then
  # firewall.conf : ADMIN_NETS="ip1 ip2 ...", SWITCH_NET="...", RESTRICT_SSH=true/false
  # shellcheck disable=SC1090
  . "$CONF"
  # ADMIN_NETS est une chaîne séparée par des espaces -> tableau.
  read -ra ADMIN_NETS <<< "${ADMIN_NETS}"
fi
# ============================================================================

IPT=iptables

echo "==> Ports web publiés par Docker (443 / 8443) via DOCKER-USER"
$IPT -N DOCKER-USER 2>/dev/null || true
$IPT -F DOCKER-USER
$IPT -A DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
# Ne PAS filtrer le trafic SORTANT des conteneurs (ex: webui -> API GreenLake
# en HTTPS/443). On laisse passer tout ce qui vient des réseaux Docker ; la
# règle DROP ne concerne ainsi que l'entrée externe vers Caddy.
for sub in $(docker network inspect $(docker network ls -q) \
             -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null); do
  $IPT -A DOCKER-USER -s "$sub" -j RETURN
done
for net in "${ADMIN_NETS[@]}"; do
  $IPT -A DOCKER-USER -s "$net" -p tcp -m multiport --dports 443,8443 -j RETURN
done
$IPT -A DOCKER-USER -p tcp -m multiport --dports 443,8443 -j DROP
$IPT -A DOCKER-USER -j RETURN

echo "==> TFTP 69/udp (host-mode) via INPUT : seulement depuis les switchs"
$IPT -D INPUT -p udp --dport 69 -j DROP 2>/dev/null || true
$IPT -A INPUT -p udp --dport 69 -s "$SWITCH_NET" -j ACCEPT
$IPT -A INPUT -p udp --dport 69 -j DROP

if [ "$RESTRICT_SSH" = "true" ]; then
  echo "==> SSH 22 du LXC : seulement depuis les postes admin"
  $IPT -D INPUT -p tcp --dport 22 -j DROP 2>/dev/null || true
  for net in "${ADMIN_NETS[@]}"; do
    $IPT -A INPUT -p tcp --dport 22 -s "$net" -j ACCEPT
  done
  $IPT -A INPUT -p tcp --dport 22 -j DROP
fi

echo
echo "✅ Pare-feu appliqué."
echo "   1) VÉRIFIE TOUT DE SUITE que tu accèdes encore (https://<ip>, terminal, SSH)."
echo "   2) Persistance au reboot :"
echo "      apt -y install iptables-persistent && netfilter-persistent save"
