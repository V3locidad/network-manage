# Déployer l'outil sur un nouveau site

Ce dépôt est le **socle générique réutilisable**. Les données propres à chaque
site (liste des switchs, identifiants, rocades) restent **locales** et ne sont
**jamais** poussées sur GitHub.

## Prérequis du site
- Un serveur/LXC Docker joignant le réseau de management des switchs
  (voir `docs/deploiement.md` pour créer un LXC Proxmox).
- `git`, `docker`, `docker compose` installés.

## Mise en route (5 minutes)

```bash
# 1. Récupérer l'outil
git clone https://github.com/<toncompte>/network-automation.git
cd network-automation

# 2. Amorcer le site (crée les fichiers locaux + secrets)
./setup-site.sh

# 3. Renseigner les 3 fichiers du site
nano inventory/hosts.yml        # les switchs (IP + groupe)
nano secret/switch_creds.yml    # compte d'accès aux switchs
nano webui/.env                 # mot de passe de l'interface

# 4. Démarrer l'interface
cd webui && docker compose up -d --build
```

Accès : `http://<ip-du-serveur>:8080`

## Ce qui est générique (partagé, dans le dépôt)
- `roles/`, `playbooks/` — la logique Ansible multi-vendor
- `webui/` — l'interface web
- `inventory/group_vars/` — méthodes de connexion par type de switch
- les `*.example` — modèles à copier

## Ce qui est local par site (git-ignoré, jamais poussé)
- `inventory/hosts.yml` — les switchs du site
- `inventory/host_vars/*.yml` — rocades (`uplink_ports`) par switch
- `secret/switch_creds.yml` — identifiants des switchs
- `webui/.env` — mot de passe de l'interface
- `backups/` — sauvegardes de config

## Mettre à jour l'outil sur un site
```bash
cd network-automation
git pull
cd webui && docker compose up -d --build   # si le code a changé
```
Tes fichiers locaux (inventaire, secrets) ne sont pas touchés par le `git pull`.
