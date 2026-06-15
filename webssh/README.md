# Terminal interactif (WebSSH)

Conteneur fournissant un **terminal SSH dans le navigateur** (xterm). Permet de
se connecter en interactif à un switch, comme avec PuTTY.

## Démarrage
```bash
cd webssh
docker compose up -d --build
```
Accès direct : `http://<ip-lxc>:8888` — tu y saisis l'IP du switch, le login et
le mot de passe, et tu obtiens une session SSH interactive.

## Intégration à l'interface
La page **« Terminal »** de l'interface web liste tes switchs avec un bouton
« Ouvrir » qui pré-remplit l'IP (et le login) dans WebSSH — tu n'as plus qu'à
taper le mot de passe.

## ⚠️ Sécurité
WebSSH donne un **accès SSH complet** à toute personne qui atteint le port 8888,
vers n'importe quel hôte joignable. À n'exposer que sur le réseau de management.
Pour durcir : le placer derrière un reverse-proxy avec authentification, ou
restreindre l'accès au port 8888 par pare-feu.
