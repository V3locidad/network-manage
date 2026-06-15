# Network Automation — gestion des switchs (Cisco / Aruba CX / ProCurve)

Gérer le parc de switchs **simplement** via Ansible, avec une **interface web
maison** utilisable par les techniciens : déployer un VLAN, sauvegarder les
configs, sortir un inventaire, activer/désactiver un port — sans toucher à la
CLI de chaque switch.

```
Technicien ─▶ Interface web (Flask) ─▶ Ansible (playbooks/roles) ─▶ Switchs
                                              ▲
                                   Inventaire (statique, puis LibreNMS)
```

> **Déploiement sur un nouveau site** : voir **[SITE_SETUP.md](SITE_SETUP.md)**.
> Ce dépôt est générique ; les données propres à un site (switchs,
> identifiants, rocades) restent locales et ne sont jamais poussées.

## Ce qui est livré

| Élément | Rôle |
|---------|------|
| `webui/` | Interface web ultra-simple (Flask + Docker) — le point d'entrée. |
| `inventory/` | Le parc, rangé par constructeur (chaque groupe = un module Ansible). |
| `roles/vlan/` | Déploiement de VLAN **multi-vendor** (aiguillage automatique). |
| `roles/port/` | Activer/désactiver un port, avec **protection des rocades**. |
| `roles/backup/` | Sauvegarde des running-config (lecture seule, sans risque). |
| `roles/facts_report/` | Rapport CSV du parc (modèle, version, série). |
| `roles/firmware/` | Mise à jour firmware (sensible, garde-fous intégrés). |
| `playbooks/` | Les actions lancées par l'interface. |
| `docs/` | Guide de déploiement LXC + inventaire LibreNMS. |

## Démarrage rapide (un site)

```bash
git clone https://github.com/<toncompte>/network-automation.git
cd network-automation
./setup-site.sh                 # crée les fichiers locaux + secrets
nano inventory/hosts.yml        # tes switchs (IP + groupe)
nano secret/switch_creds.yml    # compte d'accès aux switchs
nano webui/.env                 # mot de passe de l'interface
cd webui && docker compose up -d --build
```

Accès : `http://<ip-du-serveur>:8080`. Détails dans **[SITE_SETUP.md](SITE_SETUP.md)**.

## Actions disponibles dans l'interface

- 💾 **Sauvegarde** des configurations (lecture seule)
- 📋 **Rapport du parc** CSV (modèle, firmware, n° de série)
- 🔧 **Déployer un VLAN** (création/suppression, **mode simulation par défaut**)
- 🔌 **Activer / désactiver un port** (un seul switch, **rocades protégées**)

## Points de sécurité

- Identifiants des switchs hors dépôt (`secret/switch_creds.yml`, git-ignoré).
- Interface protégée par mot de passe.
- VLAN et port : **simulation (dry-run) cochée par défaut**.
- Port : désactivation refusée sur un **lien inter-switch (rocade)**, détecté
  via LLDP + liste blanche `uplink_ports`.
- `firmware` : `serial: 1` (un switch à la fois) + cible explicite obligatoire.

## En lecture seule d'abord

Commence toujours par la **Sauvegarde** sur un switch : zéro risque, et ça
valide la connectivité + les identifiants avant toute action en écriture.

## À venir

- 🔜 Inventaire dynamique depuis LibreNMS (voir `docs/librenms-inventory.md`)
- 🔜 Nouvelles actions (description de port, audit NTP/SNMP/Syslog…)
