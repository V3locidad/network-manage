# Interface web maison — gestion des switchs

Page web ultra-simple pour que les techniciens lancent les playbooks Ansible
sans toucher à la CLI. Gratuite, sans pub, sur le LXC.

```
Technicien → http://10.0.0.50:8080 → Flask → ansible-playbook → switchs
```

## Fonctionnalités
- **Sauvegarde des configs** (choix de la cible)
- **Rapport du parc** (CSV modèle/firmware/série)
- **Déployer un VLAN** (formulaire + case « Simulation » cochée par défaut)
- Login par mot de passe partagé, logs **en direct** (streaming SSE)

## Installation (sur le LXC)

```bash
# 1. Identifiants des switchs (hors dépôt Git)
mkdir -p /opt/net-automation/secret
cp /opt/net-automation/secret/switch_creds.example.yml \
   /opt/net-automation/secret/switch_creds.yml
nano /opt/net-automation/secret/switch_creds.yml      # ansible_user / ansible_password
chmod 600 /opt/net-automation/secret/switch_creds.yml

# 2. Config de l'interface
cd /opt/net-automation/webui
cp .env.example .env
sed -i "s|change_me_random|$(head -c32 /dev/urandom | base64)|" .env
nano .env                                              # WEBUI_PASSWORD

# 3. Build + démarrage
docker compose up -d --build
```

Accès : **http://10.0.0.50:8080**

## Notes
- L'image embarque Ansible + les collections réseau (Cisco/Aruba) : aucune
  installation au lancement, donc démarrage rapide des tâches.
- Le projet est monté en lecture seule ; les sauvegardes/rapports vont dans
  `/opt/net-automation/backups` (persistant).
