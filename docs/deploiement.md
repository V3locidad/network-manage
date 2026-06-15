# Déploiement — LXC Proxmox dédiée + Docker + Git

Objectif : une VM/LXC « net-automation » isolée qui fait tourner l'interface
web + Ansible, et pilote les switchs. LibreNMS reste intact et n'est utilisé
que via son API (inventaire).

```
┌─────────────────────┐      API REST      ┌──────────────┐
│  LXC net-automation  │ ─────────────────▶ │  LibreNMS    │
│  Interface + Ansible │                    │ (supervision)│
└─────────┬───────────┘                    └──────────────┘
          │ SSH (VLAN mgmt)
          ▼
   Switchs Cisco / Aruba CX / ProCurve
```

---

## 1. Créer le conteneur LXC sur Proxmox

Depuis le nœud Proxmox (ici pve-node), template Debian 12 :

```bash
# Récupère le template si besoin
pveam update && pveam available | grep debian-12
pveam download local debian-12-standard_*_amd64.tar.zst

# Crée le conteneur (ajuste storage, VMID, pont/VLAN mgmt = VLAN10)
pct create 120 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname net-automation \
  --cores 2 --memory 2048 --swap 512 \
  --rootfs local-lvm:12 \
  --net0 name=eth0,bridge=vmbrX,tag=10,ip=10.0.0.50/24,gw=10.0.0.254 \
  --features nesting=1,keyctl=1 \
  --unprivileged 1 \
  --onboot 1

pct start 120
pct enter 120
```

> ⚠️ **`nesting=1` et `keyctl=1` sont indispensables** pour faire tourner
> Docker dans un LXC non privilégié.
> L'IP `10.0.0.50` doit être sur le **VLAN 10 de management des switchs**
> (10.0.0.0/24). Adapte `bridge=` au pont Proxmox qui porte le VLAN 10 et
> `gw=` à la passerelle réelle du VLAN 10.

## 2. Préparer le conteneur

```bash
apt update && apt -y upgrade
apt -y install git curl ca-certificates

# Docker (méthode officielle)
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker --version && docker compose version
```

## 3. Récupérer l'outil sur le LXC

```bash
cd /opt
git clone https://github.com/<toncompte>/network-automation.git net-automation
cd net-automation
```

Mises à jour ultérieures : `git pull` (tes fichiers locaux ne sont pas touchés).

## 4. Amorcer le site + lancer l'interface

```bash
./setup-site.sh                 # crée inventory/hosts.yml, secrets, .env
nano inventory/hosts.yml        # les switchs du site
nano secret/switch_creds.yml    # compte d'accès aux switchs
nano webui/.env                 # mot de passe de l'interface

cd webui && docker compose up -d --build
```

Accès : `http://10.0.0.50:8080`. Détails complets dans `SITE_SETUP.md`.

## 5. Vérifier la connectivité réseau

Depuis le LXC, avant tout playbook :

```bash
# Le LXC doit joindre les switchs (SSH) et l'API LibreNMS (HTTPS)
ping -c2 10.0.0.11        # un switch (VLAN 10)
curl -k https://<librenms>/api/v0/devices \
  -H "X-Auth-Token: <token>"  # API LibreNMS (étape inventaire dynamique)
```

Si le ping switch échoue → vérifier le `tag=10` de l'interface LXC, le pont
Proxmox utilisé, et la route mgmt vers le VLAN 10 (10.0.0.0/24).

## 6. Intégration LibreNMS (étape 2)

Une fois l'interface opérationnelle avec l'inventaire statique, passe à
`docs/librenms-inventory.md` pour générer l'inventaire automatiquement
depuis l'API LibreNMS (plus de double saisie).

---

## Sauvegarde du LXC

Pense à inclure le conteneur 120 dans tes backups Proxmox (vzdump).
Pense aussi à `/opt/net-automation/backups` (sauvegardes de config) et aux
fichiers locaux (`inventory/hosts.yml`, `secret/`, `webui/.env`).
```
