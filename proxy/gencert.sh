#!/usr/bin/env bash
# Génère un certificat auto-signé pour Caddy, avec les IP du LXC en SAN.
# Usage : ./gencert.sh <ip1> [ip2] ...
#   ex :  ./gencert.sh 10.0.0.50 172.16.0.5
set -euo pipefail
cd "$(dirname "$0")"

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <ip1> [ip2] ...   (toutes les IP par lesquelles tu accèdes)"
  exit 1
fi

SAN=""
for ip in "$@"; do SAN="${SAN}${SAN:+,}IP:${ip}"; done

mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=net-automation" -addext "subjectAltName=${SAN}"

echo "✅ Certificat généré dans certs/ pour : ${SAN}"
echo "   Recrée Caddy :  docker compose up -d --force-recreate"
