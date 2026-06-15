# Inventaire dynamique depuis LibreNMS (étape 2)

LibreNMS connaît déjà tous tes switchs. Plutôt que de maintenir
`inventory/hosts.yml` à la main, tu peux le générer depuis son API.

## Principe

LibreNMS expose une API REST (`/api/v0/devices`). Un petit script
d'inventaire dynamique récupère les devices et les range dans les groupes
Ansible (`cisco_ios`, `aruba_cx`, `procurve`…) selon leur `os` / `sysDescr`.

## Mise en place

1. Dans LibreNMS : **Settings → API → Create API token**.
2. Crée `inventory/librenms.yml` :

```yaml
plugin: ansible.builtin.constructed   # ou un script custom (voir ci-dessous)
```

3. Le plus simple : un script `inventory/librenms_inventory.py` qui appelle
   l'API et émet du JSON au format inventaire Ansible. Mapping conseillé :

| LibreNMS `os`        | Groupe Ansible |
|----------------------|----------------|
| `ios`, `iosxe`       | `cisco_ios`    |
| `nxos`               | `cisco_nxos`   |
| `arubaos-cx`         | `aruba_cx`     |
| `procurve`, `arubaos`| `procurve`     |

4. Utilisation :

```bash
ansible-inventory -i inventory/librenms_inventory.py --graph
ansible-playbook -i inventory/librenms_inventory.py playbooks/backup_config.yml
```

> Quand tu seras prêt pour cette étape, demande-moi : je te génère le script
> `librenms_inventory.py` complet avec le mapping ci-dessus et la pagination API.
