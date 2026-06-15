#!/usr/bin/env python3
"""Interface web ultra-simple pour lancer les playbooks Ansible du parc switchs.

3 actions : Sauvegarde, Rapport du parc, Déployer un VLAN.
Login partagé, logs en direct (SSE). Aucune dépendance externe lourde.
"""
import base64
import glob
import json
import os
import queue
import re
import subprocess
import threading
import uuid
from functools import wraps

import yaml
from flask import (Flask, Response, redirect, render_template, request,
                   session, url_for)

PROJECT_DIR = "/project"          # dépôt monté en lecture seule
CREDS_FILE = "/secret/switch_creds.yml"   # ansible_user / ansible_password
INVENTORY = os.path.join(PROJECT_DIR, "inventory/hosts.yml")

APP_PASSWORD = os.environ.get("WEBUI_PASSWORD", "changeme")

app = Flask(__name__)
app.secret_key = os.environ.get("WEBUI_SECRET", "dev-secret-change-me")


@app.after_request
def no_cache(resp):
    """Évite que le navigateur garde d'anciennes pages en cache."""
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store"
    return resp

# Registre des exécutions en cours : run_id -> {"q": Queue, "done": bool}
RUNS = {}

# Définition des actions exposées dans l'interface.
ACTIONS = {
    "backup": {
        "label": "Sauvegarde des configs",
        "playbook": "playbooks/backup_config.yml",
        "icon": "💾",
        "desc": "Récupère et archive la configuration des switchs.",
    },
    "report": {
        "label": "Rapport du parc",
        "playbook": "playbooks/facts_report.yml",
        "icon": "📋",
        "desc": "Génère le CSV (modèle, firmware, n° de série).",
    },
    "vlan": {
        "label": "Déployer un VLAN",
        "playbook": "playbooks/deploy_vlan.yml",
        "icon": "🔧",
        "desc": "Crée ou supprime un VLAN sur les switchs choisis.",
    },
    "port": {
        "label": "Activer / désactiver un port",
        "playbook": "playbooks/port.yml",
        "icon": "🔌",
        "desc": "Active ou coupe un port (ou une plage) sur un switch.",
    },
    "firmware": {
        "label": "Mise à jour firmware",
        "playbook": "playbooks/firmware.yml",
        "icon": "⬆️",
        "desc": "Met à jour l'OS d'un switch (via TFTP). Reboot — un switch à la fois.",
    },
    "stdconfig": {
        "label": "Config standard",
        "playbook": "playbooks/stdconfig.yml",
        "icon": "🛡️",
        "desc": "NTP/SNMP/logging + sécurité des ports d'accès (STP, BPDU, loop-protect).",
    },
    "access": {
        "label": "Port → VLAN d'accès",
        "playbook": "playbooks/access.yml",
        "icon": "🔀",
        "desc": "Place un port en accès (untagged) dans un VLAN. Rocades protégées.",
    },
    "cmd": {
        "label": "Envoyer des commandes",
        "playbook": "playbooks/cmd.yml",
        "icon": "⌨️",
        "desc": "Exécute des commandes libres sur les switchs (show, config…).",
    },
    # Action sans carte : collecte la liste des VLANs pour le menu déroulant.
    "vlan_list": {
        "label": "Collecte des VLANs",
        "playbook": "playbooks/vlan_list.yml",
        "icon": "",
        "desc": "",
    },
    # Action sans carte : collecte des versions pour la page « État firmware ».
    "firmware_status": {
        "label": "Collecte des versions firmware",
        "playbook": "playbooks/firmware_status.yml",
        "icon": "",
        "desc": "",
    },
    # Action sans carte : audit de conformité (alimente la page « Conformité »).
    "audit": {
        "label": "Audit de conformité",
        "playbook": "playbooks/audit.yml",
        "icon": "",
        "desc": "",
    },
}

FIRMWARE_IMAGES_DIR = os.path.join(PROJECT_DIR, "firmware", "images")
FIRMWARE_STATUS_JSON = "/backups/firmware_status.json"


def swi_to_version(filename):
    """WC_16_11_0014.swi -> WC.16.11.0014 (la version est encodée dans le nom)."""
    return filename.rsplit(".swi", 1)[0].replace("_", ".")


def load_switch_hosts():
    """Liste [{name, ip}] des switchs depuis l'inventaire."""
    out = []
    try:
        with open(INVENTORY) as fh:
            inv = yaml.safe_load(fh)
        for grp in inv["all"]["children"].values():
            for name, vals in (grp.get("hosts") or {}).items():
                out.append({"name": name,
                            "ip": (vals or {}).get("ansible_host", "")})
    except Exception:
        pass
    return sorted(out, key=lambda h: h["name"])


def switch_creds():
    """(login, mot de passe) des switchs, pour pré-remplir le terminal."""
    try:
        with open(CREDS_FILE) as fh:
            d = yaml.safe_load(fh) or {}
        return d.get("ansible_user", ""), d.get("ansible_password", "")
    except Exception:
        return "", ""


def load_vlans():
    """Liste des VLANs [{id, name}] collectée par playbooks/vlan_list.yml."""
    try:
        with open("/backups/vlans.json") as fh:
            data = json.load(fh)
        return sorted(data, key=lambda v: int(v.get("id", 0)))
    except (OSError, ValueError):
        return []


def load_targets():
    """Cibles proposées sous forme (valeur, libellé) : groupes puis hôtes."""
    hosts = []
    try:
        with open(INVENTORY) as fh:
            inv = yaml.safe_load(fh)
        for grp in inv["all"]["children"].values():
            for host in (grp.get("hosts") or {}):
                if host not in hosts:
                    hosts.append(host)
    except Exception:
        pass
    # Libellés clairs pour les groupes, puis chaque switch individuellement.
    targets = [
        ("procurve", f"Tous les switchs ({len(hosts)})"),
        ("switches", "Tout le parc (tous constructeurs)"),
    ]
    targets += [(h, h) for h in hosts]
    return targets


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["auth"] = True
            return redirect(url_for("index"))
        error = "Mot de passe incorrect."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    targets = load_targets()
    # Pour l'action "port" : uniquement des switchs individuels (pas de groupe).
    hosts = [t for t in targets if t[0] not in ("procurve", "switches")]
    return render_template("index.html", actions=ACTIONS,
                           targets=targets, hosts=hosts, vlans=load_vlans())


@app.route("/firmware")
@login_required
def firmware_dashboard():
    # Image(s) de référence déposée(s) sur le TFTP -> version cible.
    images = []
    for path in sorted(glob.glob(os.path.join(FIRMWARE_IMAGES_DIR, "*.swi"))):
        name = os.path.basename(path)
        images.append({"file": name, "version": swi_to_version(name)})
    target = max((i["version"] for i in images), default=None)

    # Versions collectées sur les switchs (dernier scan).
    data = []
    try:
        with open(FIRMWARE_STATUS_JSON) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = []

    rows, n_ok, n_old = [], 0, 0
    for d in data:
        cur = (d.get("version") or "?").strip()
        if not target:
            status = "noref"
        elif cur in ("", "?"):
            status = "unknown"
        elif cur == target:
            status = "ok"
            n_ok += 1
        else:
            status = "outdated"
            n_old += 1
        rows.append({"host": d.get("host", "?"), "ip": d.get("ip", ""),
                     "version": cur, "status": status})
    rows.sort(key=lambda r: r["host"])
    return render_template("firmware.html", rows=rows, images=images,
                           target=target, n_ok=n_ok, n_old=n_old,
                           scanned=bool(data))


@app.route("/terminal")
@login_required
def terminal():
    # WebSSH tourne sur le même hôte, port 8888.
    host = request.host.split(":")[0]
    # Terminal servi par Caddy en HTTPS + auth sur le port 8443.
    webssh = os.environ.get("WEBSSH_URL", "https://%s:8443" % host)
    user, _pw = switch_creds()
    return render_template("terminal.html", hosts=load_switch_hosts(),
                           webssh=webssh, user=user)


@app.route("/console")
@login_required
def console_result():
    try:
        with open("/backups/cmd_result.json") as fh:
            report = json.load(fh)
    except (OSError, ValueError):
        report = []
    return render_template("console.html", report=report)


@app.route("/audit")
@login_required
def audit_dashboard():
    try:
        with open("/backups/audit.json") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = []
    # Contrôles pris en compte (True = conforme).
    checks = ["ntp", "logging", "snmp_overall", "web_mgmt", "authmgr", "portsec"]
    rows, n_ok = [], 0
    for d in data:
        d["snmp_overall"] = bool(d.get("snmp")) and bool(d.get("snmp_public"))
        ecarts = [c for c in checks if not d.get(c)]
        d["ecarts"] = len(ecarts)
        d["ok"] = (len(ecarts) == 0)
        if d["ok"]:
            n_ok += 1
        rows.append(d)
    rows.sort(key=lambda r: r.get("host", ""))
    return render_template("audit.html", rows=rows, n_ok=n_ok,
                           total=len(rows), scanned=bool(data))


def build_command(action, form):
    """Construit la commande ansible-playbook à partir du formulaire."""
    playbook = ACTIONS[action]["playbook"]
    extra = {"target": form.get("target", "procurve")}
    if action == "vlan":
        extra.update({
            "vlan_id": form.get("vlan_id", ""),
            "vlan_name": form.get("vlan_name", ""),
            "vlan_state": form.get("vlan_state", "present"),
            # Case cochée -> le navigateur envoie une valeur (dry-run actif).
            # Case décochée -> rien n'est envoyé -> écriture réelle.
            "vlan_dry_run": bool(form.get("vlan_dry_run")),
        })
    if action == "port":
        extra.update({
            "port_id": form.get("port_id", ""),
            "port_state": form.get("port_state", "disable"),
            "port_dry_run": bool(form.get("port_dry_run")),
        })
    if action == "firmware":
        extra.update({
            "firmware_image": form.get("firmware_image", ""),
            "firmware_target_version": form.get("firmware_target_version", ""),
            "firmware_check": bool(form.get("firmware_check")),
            # Le serveur TFTP = le LXC lui-même (configuré dans webui/.env).
            "firmware_tftp_server": os.environ.get("TFTP_SERVER", ""),
        })
    if action == "stdconfig":
        extra.update({
            "baseline_dry_run": bool(form.get("baseline_dry_run")),
        })
    if action == "access":
        extra.update({
            "access_vlan_id": form.get("access_vlan_id", ""),
            "access_port_id": form.get("access_port_id", ""),
            "access_dry_run": bool(form.get("access_dry_run")),
        })
    if action == "cmd":
        lines = [ln.strip() for ln in form.get("commands", "").splitlines()
                 if ln.strip()]
        extra["commands"] = lines
    cmd = ["ansible-playbook", playbook,
           "-e", f"@{CREDS_FILE}",
           "-e", json.dumps(extra)]
    return cmd


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def run_job(run_id, cmd):
    q = RUNS[run_id]["q"]
    env = dict(os.environ,
               HOME="/tmp", ANSIBLE_HOME="/tmp/.ansible",
               ANSIBLE_LOG_PATH="/tmp/ansible.log",
               ANSIBLE_HOST_KEY_CHECKING="False")
    q.put("$ " + " ".join(cmd) + "\n\n")
    try:
        proc = subprocess.Popen(cmd, cwd=PROJECT_DIR, env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        for line in proc.stdout:
            q.put(ANSI_RE.sub("", line).replace("\r", ""))
        proc.wait()
        q.put(f"\n=== Terminé (code {proc.returncode}) ===\n")
    except Exception as exc:  # noqa: BLE001
        q.put(f"\n[ERREUR lancement] {exc}\n")
    RUNS[run_id]["done"] = True
    q.put(None)  # sentinelle de fin


@app.route("/run/<action>", methods=["POST"])
@login_required
def run(action):
    if action not in ACTIONS:
        return "Action inconnue", 404
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {"q": queue.Queue(), "done": False}
    cmd = build_command(action, request.form)
    threading.Thread(target=run_job, args=(run_id, cmd), daemon=True).start()
    # Après une collecte (versions / VLANs), on revient automatiquement à la page.
    if action == "firmware_status":
        back = url_for("firmware_dashboard")
    elif action == "audit":
        back = url_for("audit_dashboard")
    elif action == "cmd":
        back = url_for("console_result")
    else:
        back = url_for("index")
    return render_template("run.html", run_id=run_id,
                           action=ACTIONS[action]["label"], back=back,
                           auto_redirect=(action in ("firmware_status", "vlan_list",
                                                     "audit", "cmd")))


@app.route("/stream/<run_id>")
@login_required
def stream(run_id):
    info = RUNS.get(run_id)
    if not info:
        return "Run inconnu", 404

    def gen():
        while True:
            line = info["q"].get()
            if line is None:
                yield "event: end\ndata: fin\n\n"
                break
            for sub in line.rstrip("\n").split("\n"):
                yield f"data: {sub}\n\n"
    return Response(gen(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
