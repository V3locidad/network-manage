# Serveur TFTP — images firmware

Conteneur TFTP pour servir les images firmware (`.swi`) aux switchs lors des
mises à jour.

## Démarrage
```bash
cd firmware
docker compose up -d --build
```
Le serveur écoute sur **l'IP du LXC, port 69/udp** (mode `network_mode: host`).

## Déposer une image
Copie le fichier `.swi` dans `firmware/images/` :
```bash
cp WC_16_11_0014.swi /opt/net-automation/firmware/images/
```
Il sera servi à la racine TFTP (le switch le télécharge par son seul nom).

> Les `.swi` ne sont **pas** versionnés (gros binaires, voir `.gitignore`).

## Vérifier
Depuis une machine du réseau de management :
```bash
tftp <ip-lxc> -c get WC_16_11_0014.swi   # doit télécharger le fichier
```

## Sécurité
Le partage est en **lecture seule** et limité au dossier `images/`. À n'exposer
que sur le réseau de management des switchs.
