# Durcissement — mise en place

Objectif : tout passe par un reverse proxy **HTTPS** (Caddy), le terminal
WebSSH est **protégé par mot de passe**, et seuls tes postes d'admin / VPN
peuvent atteindre l'interface. Les conteneurs webui et webssh ne publient
**plus** de port directement (uniquement via Caddy).

```
Admin / VPN ─HTTPS─▶ Caddy ─┬─▶ webui   (:8080 interne)
                            └─▶ webssh  (:8888 interne, + auth Caddy)
Switchs ──TFTP/69──▶ LXC (firmware)
```

> 🛟 Filet de sécurité : en cas de souci d'accès, la **console Proxmox**
> (`pct enter <CTID>` depuis l'hôte) reste toujours disponible.

## Ordre de déploiement (à suivre tel quel)

### 1. Récupérer le code + permissions des secrets
```bash
# Mac
rsync -av --exclude '.venv' --exclude 'vault.yml' \
  /Users/julien/network-automation/ root@10.0.0.50:/opt/net-automation/
# LXC
chmod 600 /opt/net-automation/secret/switch_creds.yml \
          /opt/net-automation/inventory/group_vars/all/site.yml \
          /opt/net-automation/webui/.env
```

### 2. Réseau Docker partagé (une seule fois)
```bash
docker network create netauto
```

### 3. Recréer webui et webssh (sans port publié, sur le réseau partagé)
```bash
cd /opt/net-automation/webui  && docker compose up -d --build
cd /opt/net-automation/webssh && docker compose up -d --build
```

### 4. Configurer + lancer Caddy
```bash
cd /opt/net-automation/proxy
cp .env.example .env
# Génère le hash du mot de passe d'accès au terminal :
docker run --rm caddy caddy hash-password --plaintext 'TON_MDP_TERMINAL'
# Colle la valeur dans .env (WEBSSH_HASH=...), en DOUBLANT les $ -> $$
nano .env
docker compose up -d
```

### 5. Tester l'accès AVANT le pare-feu
- Interface : `https://10.0.0.50` (accepte l'avertissement de certificat auto-signé)
- Terminal : depuis l'interface → onglet **Terminal** → **Ouvrir** (Caddy demande
  l'identifiant `admin` + le mot de passe du terminal, puis WebSSH s'ouvre).

### 6. Pare-feu (en dernier, une fois l'accès confirmé)
```bash
nano /opt/net-automation/security/firewall.sh   # règle ADMIN_NETS (VPN + .240)
bash /opt/net-automation/security/firewall.sh
# Vérifie que tu accèdes toujours, puis rends persistant :
apt -y install iptables-persistent && netfilter-persistent save
```

## Ce qui change pour toi
- L'interface passe de `http://…:8080` à **`https://10.0.0.50`**
  (mets à jour ton favori). Avertissement de certificat = normal (auto-signé) ;
  tu peux installer le CA interne de Caddy pour le supprimer.
- Le terminal demande un mot de passe (auth Caddy) — fini l'accès libre.
- Le mot de passe switch n'est plus dans l'URL du terminal.

## Pour aller plus loin (optionnel)
- `RESTRICT_SSH=true` dans `firewall.sh` pour limiter aussi le SSH du LXC.
- Chiffrer les secrets avec `ansible-vault` plutôt que des fichiers en clair.
- Installer le certificat racine de Caddy sur les postes admin (plus d'avertissement).
