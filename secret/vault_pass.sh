#!/usr/bin/env bash
# Client de mot de passe Ansible Vault.
# Ansible exécute ce script (s'il est exécutable) et utilise sa sortie comme
# mot de passe vault. Le mot de passe vient de la variable d'environnement
# ANSIBLE_VAULT_PASSWORD (définie dans webui/.env, hors dépôt Git).
printf '%s' "${ANSIBLE_VAULT_PASSWORD:-}"
