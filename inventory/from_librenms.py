#!/usr/bin/env python3
"""Génère inventory/hosts.yml à partir de l'API LibreNMS.

Détecte le constructeur de chaque équipement via son champ `os` et le range
dans le bon groupe Ansible (cisco_ios / cisco_nxos / aruba_cx / procurve).

Variables d'environnement :
  LNMS_URL    ex : http://10.0.0.250   (sans /api/v0)
  LNMS_TOKEN  jeton API (Settings -> API -> Create token)
  LNMS_ONLY_UP  (optionnel) "1" = ignorer les équipements down

Usage :
  from_librenms.py [chemin_de_sortie]      (défaut: inventory/hosts.yml)
"""
import json
import os
import sys
import urllib.request

# Mapping os LibreNMS -> groupe Ansible (cf. group_vars/).
OS_TO_GROUP = {
    "ios": "cisco_ios",
    "iosxe": "cisco_ios",
    "iosxr": "cisco_ios",
    "nxos": "cisco_nxos",
    "arubaos-cx": "aruba_cx",
    "aoscx": "aruba_cx",
    "arubaos": "procurve",
    "procurve": "procurve",
}
GROUPS = ["cisco_ios", "cisco_nxos", "aruba_cx", "procurve"]


def api_get(base, token, path):
    req = urllib.request.Request(base.rstrip("/") + path,
                                 headers={"X-Auth-Token": token})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def strip_domain(name):
    """Retire le suffixe de domaine d'un FQDN ('SWI-X.A-KASTLER' -> 'SWI-X').
    Cisco met le domaine dans son sysName, pas Aruba/ProCurve. On préserve les
    adresses IP (a.b.c.d) utilisées en repli."""
    parts = (name or "").split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return name          # c'est une IP -> on ne tronque pas
    return parts[0] if parts else name


def sanitize(name):
    """Nom d'hôte Ansible : lettres/chiffres/_/-/. uniquement."""
    out = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in name)
    return out.strip("-") or "switch"


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "inventory/hosts.yml"
    base = os.environ.get("LNMS_URL", "").strip()
    token = os.environ.get("LNMS_TOKEN", "").strip()
    only_up = os.environ.get("LNMS_ONLY_UP", "") == "1"
    if not base or not token:
        sys.exit("ERREUR : LNMS_URL et LNMS_TOKEN doivent être définis.")

    data = api_get(base, token, "/api/v0/devices")
    devices = data.get("devices", [])

    grouped = {g: {} for g in GROUPS}
    skipped = []
    for d in devices:
        os_name = (d.get("os") or "").lower()
        group = OS_TO_GROUP.get(os_name)
        if not group:
            skipped.append("%s (os=%s)" % (d.get("hostname", "?"), os_name))
            continue
        if only_up and d.get("status") == 0:
            continue
        ip = d.get("ip") or d.get("hostname") or ""
        # Nom lisible : sysName si dispo, sinon hostname. Domaine retiré (Cisco),
        # mis en MAJUSCULES.
        name = sanitize(strip_domain(d.get("sysName") or d.get("hostname") or ip)).upper()
        if not ip:
            skipped.append("%s (pas d'IP)" % name)
            continue
        grouped[group][name] = ip

    # --- Écriture du YAML (à la main, pour rester lisible et sans dépendance) ---
    lines = ["---",
             "# Généré automatiquement depuis LibreNMS — ne pas éditer à la main.",
             "all:", "  children:"]
    total = 0
    for g in GROUPS:
        lines.append("    %s:" % g)
        hosts = grouped[g]
        if hosts:
            lines.append("      hosts:")
            for name, ip in sorted(hosts.items()):
                lines.append("        %s: { ansible_host: %s }" % (name, ip))
            total += len(hosts)
        else:
            lines.append("      hosts: {}")
    lines += ["    switchs:", "      children:"]
    lines += ["        %s:" % g for g in GROUPS]
    lines.append("")

    with open(out_path, "w") as fh:
        fh.write("\n".join(lines))

    print("✅ %d équipement(s) écrit(s) dans %s" % (total, out_path))
    for g in GROUPS:
        if grouped[g]:
            print("   - %s : %d" % (g, len(grouped[g])))
    if skipped:
        print("⚠️  %d ignoré(s) (os non reconnu / sans IP) :" % len(skipped))
        for s in skipped[:20]:
            print("     · %s" % s)


if __name__ == "__main__":
    main()
