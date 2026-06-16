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
from datetime import datetime
from functools import wraps

import yaml
from flask import (Flask, Response, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

PROJECT_DIR = "/project"          # dépôt monté en lecture seule
CREDS_FILE = "/secret/switch_creds.yml"   # ansible_user / ansible_password
USERS_FILE = "/backups/users.json"        # comptes individuels (inscriptible)
INVENTORY = os.path.join(PROJECT_DIR, "inventory/hosts.yml")

APP_PASSWORD = os.environ.get("WEBUI_PASSWORD", "changeme")

# Verrou pour les écritures concurrentes du fichier de comptes.
_users_lock = threading.Lock()


def load_users():
    """Comptes {login: {hash, must_change}}. Vide => mode mot de passe partagé."""
    try:
        with open(USERS_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for login, val in data.items():
        # Tolère l'ancien format {login: "<hash>"}.
        if isinstance(val, str):
            out[login] = {"hash": val, "must_change": False}
        elif isinstance(val, dict) and val.get("hash"):
            out[login] = {"hash": val["hash"],
                          "must_change": bool(val.get("must_change"))}
    return out


def save_users(users):
    """Écrit le fichier de comptes (sous verrou)."""
    with _users_lock:
        try:
            with open(USERS_FILE, "w") as fh:
                json.dump(users, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

app = Flask(__name__)
app.secret_key = os.environ.get("WEBUI_SECRET", "dev-secret-change-me")


@app.context_processor
def inject_mode():
    """Expose aux templates : mode comptes + LibreNMS configuré."""
    return {"accounts_mode": bool(load_users()),
            "librenms_configured": bool(os.environ.get("LNMS_URL")
                                        and os.environ.get("LNMS_TOKEN"))}


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
    # Action sans carte : restauration d'une sauvegarde (page « Restauration »).
    "restore": {
        "label": "Restauration de configuration",
        "playbook": "playbooks/restore_config.yml",
        "icon": "",
        "desc": "",
    },
    # Action sans carte : collecte stack/trunks (page « Trunks »).
    "trunks": {
        "label": "Collecte stack / trunks",
        "playbook": "playbooks/trunks.yml",
        "icon": "",
        "desc": "",
    },
}

FIRMWARE_IMAGES_DIR = os.path.join(PROJECT_DIR, "firmware", "images")
FIRMWARE_STATUS_JSON = "/backups/firmware_status.json"
BACKUP_DIR = "/backups"
HISTORY_JSON = "/backups/history.json"
HISTORY_MAX = 500   # on ne garde que les N dernières entrées

# Réglages de la « config standard » (role baseline), éditables dans l'UI.
SITE_YML = os.path.join(PROJECT_DIR, "inventory/group_vars/all/site.yml")
BASELINE_JSON = "/backups/baseline.json"
BASELINE_DEFAULTS = {
    "ntp_server": "", "logging_server": "",
    "snmp_community": "", "snmp_contact": "", "snmp_location": "",
    # Plusieurs communautés : [{name, access}] à configurer, [noms] à retirer.
    "snmp_communities": [], "snmp_remove_communities": [],
    "authorized_manager": "", "protected_vlans": [],
    "loop_protect_disable_timer": 300,
    # Bannière MOTD — propre à chaque site, reste local (jamais sur GitHub).
    "banner_motd": "",
    # Interrupteurs : appliquer ou non chaque bloc.
    "baseline_ntp": True, "baseline_logging": True, "baseline_snmp": True,
    "baseline_web_mgmt_off": True, "baseline_authmgr": True,
    "baseline_banner": True,
    "baseline_spanning_tree": True, "baseline_loop_protect": True,
}
_baseline_lock = threading.Lock()


def load_baseline():
    """Réglages baseline : défauts < site.yml (si présent) < baseline.json (UI)."""
    data = dict(BASELINE_DEFAULTS)
    try:
        with open(SITE_YML) as fh:
            sy = yaml.safe_load(fh) or {}
        # snmp_location volontairement EXCLU : propre à chaque switch, on ne le
        # pré-remplit pas (sinon l'appliquer à tous écraserait les localisations).
        for k in ("ntp_server", "logging_server", "snmp_community",
                  "snmp_contact", "authorized_manager",
                  "protected_vlans", "loop_protect_disable_timer"):
            if k in sy and sy[k] not in (None, ""):
                data[k] = sy[k]
    except (OSError, ValueError):
        pass
    try:
        with open(BASELINE_JSON) as fh:
            data.update(json.load(fh))
    except (OSError, ValueError):
        pass
    # Migration : une communauté unique -> liste (rétro-compat site.yml/ancien JSON).
    if not data.get("snmp_communities") and data.get("snmp_community"):
        data["snmp_communities"] = [{"name": data["snmp_community"],
                                     "access": "restricted"}]
    # Localisation SNMP retirée de l'UI : propre à chaque switch, jamais gérée ici
    # (on neutralise toute valeur héritée d'un ancien baseline.json/site.yml).
    data["snmp_location"] = ""
    return data


def save_baseline(data):
    with _baseline_lock:
        try:
            with open(BASELINE_JSON, "w") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

# Verrou pour les écritures concurrentes du journal d'actions.
_history_lock = threading.Lock()


def load_history():
    """Journal des actions, du plus récent au plus ancien."""
    try:
        with open(HISTORY_JSON) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = []
    return list(reversed(data))


def log_history_start(run_id, who, ip, action, target, summary):
    """Enregistre le lancement d'une action (statut « en cours »)."""
    entry = {
        "run_id": run_id,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "who": who or "—",
        "ip": ip or "",
        "action": action,
        "target": target,
        "summary": summary,
        "status": "en cours",
        "rc": None,
    }
    with _history_lock:
        try:
            with open(HISTORY_JSON) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = []
        data.append(entry)
        data = data[-HISTORY_MAX:]
        try:
            with open(HISTORY_JSON, "w") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass


def log_history_finish(run_id, rc):
    """Met à jour l'entrée correspondante avec le résultat final."""
    with _history_lock:
        try:
            with open(HISTORY_JSON) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        for entry in reversed(data):
            if entry.get("run_id") == run_id:
                entry["rc"] = rc
                entry["status"] = "OK" if rc == 0 else "échec"
                break
        try:
            with open(HISTORY_JSON, "w") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass


def client_ip():
    """IP réelle du client (derrière le reverse proxy Caddy)."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def action_summary(action, form):
    """Résumé lisible des paramètres d'une action, pour le journal."""
    f = form.get
    dry = " (simulation)"
    if action == "vlan":
        s = "VLAN %s « %s » → %s" % (f("vlan_id", "?"), f("vlan_name", ""),
                                     f("vlan_state", "present"))
        return s + (dry if f("vlan_dry_run") else "")
    if action == "port":
        s = "port %s → %s" % (f("port_id", "?"), f("port_state", "disable"))
        return s + (dry if f("port_dry_run") else "")
    if action == "access":
        s = "port %s → VLAN d'accès %s" % (f("access_port_id", "?"),
                                           f("access_vlan_id", "?"))
        return s + (dry if f("access_dry_run") else "")
    if action == "firmware":
        return "image %s" % f("firmware_image", "?")
    if action == "stdconfig":
        return "config standard" + (dry if f("baseline_dry_run") else "")
    if action == "cmd":
        cmds = [ln.strip() for ln in f("commands", "").splitlines() if ln.strip()]
        return "; ".join(cmds)[:120]
    return ""


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
    """(login, mot de passe) des switchs, pour pré-remplir le terminal.

    Gère le cas où switch_creds.yml est chiffré avec Ansible Vault : on le
    déchiffre via `ansible-vault view` (le mot de passe vient de l'env)."""
    try:
        with open(CREDS_FILE) as fh:
            head = fh.readline()
            if head.startswith("$ANSIBLE_VAULT"):
                out = subprocess.run(
                    ["ansible-vault", "view", CREDS_FILE],
                    cwd=PROJECT_DIR, capture_output=True, text=True)
                d = yaml.safe_load(out.stdout) or {}
            else:
                fh.seek(0)
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


def load_host_backups():
    """{host: [{file, when}]} des sauvegardes .cfg disponibles, plus récentes d'abord."""
    out = {}
    for path in glob.glob(os.path.join(BACKUP_DIR, "*", "*.cfg")):
        host = os.path.basename(os.path.dirname(path))
        out.setdefault(host, []).append({
            "file": os.path.basename(path),
            "when": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
            "mtime": os.path.getmtime(path),
        })
    for host in out:
        out[host].sort(key=lambda b: b["mtime"], reverse=True)
    return dict(sorted(out.items()))


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
    users = load_users()
    accounts = bool(users)   # True = comptes individuels, False = mot de passe partagé
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if accounts:
            # Authentification par compte : l'identité est vérifiée, infalsifiable.
            typed = (request.form.get("who") or "").strip()
            # Identifiant insensible à la casse : on retrouve l'orthographe
            # canonique du compte pour toujours journaliser la même valeur.
            canonical = next((k for k in users if k.lower() == typed.lower()), None)
            u = users.get(canonical) if canonical else None
            if u and check_password_hash(u["hash"], pwd):
                session["auth"] = True
                session["who"] = canonical
                if u.get("must_change"):
                    # Mot de passe par défaut -> changement obligatoire.
                    session["force_change"] = True
                    return redirect(url_for("change_password"))
                return redirect(url_for("dashboard"))
            error = "Identifiant ou mot de passe incorrect."
        else:
            # Rétro-compatibilité : mot de passe partagé + nom libre (non vérifié).
            if pwd == APP_PASSWORD:
                session["auth"] = True
                session["who"] = (request.form.get("who") or "").strip()[:40]
                return redirect(url_for("dashboard"))
            error = "Mot de passe incorrect."
    return render_template("login.html", error=error, accounts=accounts)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/_authcheck", methods=["GET", "POST", "HEAD", "OPTIONS",
                                   "PUT", "DELETE", "PATCH"])
def authcheck():
    """Sonde d'authentification pour le reverse proxy (forward_auth).
    200 si l'utilisateur est connecté à la webui, 401 sinon. Permet de
    protéger le terminal WebSSH (:8443) avec le MÊME login que l'interface."""
    if session.get("auth"):
        return ("", 200)
    return ("non authentifié", 401)


@app.before_request
def force_password_change():
    """Tant que le mot de passe par défaut n'est pas changé, on bloque tout
    sauf la page de changement, la déconnexion et les fichiers statiques."""
    if session.get("auth") and session.get("force_change"):
        if request.endpoint not in ("change_password", "logout", "static"):
            return redirect(url_for("change_password"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    error = None
    forced = bool(session.get("force_change"))
    if request.method == "POST":
        users = load_users()
        login_name = session.get("who")
        u = users.get(login_name)
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        if not u:
            error = "Compte introuvable."
        elif not forced and not check_password_hash(u["hash"], current):
            error = "Mot de passe actuel incorrect."
        elif len(new) < 8:
            error = "Le nouveau mot de passe doit faire au moins 8 caractères."
        elif new != confirm:
            error = "La confirmation ne correspond pas."
        elif check_password_hash(u["hash"], new):
            error = "Le nouveau mot de passe doit être différent de l'ancien."
        else:
            u["hash"] = generate_password_hash(new)
            u["must_change"] = False
            users[login_name] = u
            save_users(users)
            session.pop("force_change", None)
            return redirect(url_for("dashboard"))
    return render_template("change_password.html", error=error, forced=forced)


@app.route("/")
@login_required
def index():
    targets = load_targets()
    # Pour l'action "port" : uniquement des switchs individuels (pas de groupe).
    hosts = [t for t in targets if t[0] not in ("procurve", "switches")]
    return render_template("index.html", actions=ACTIONS,
                           targets=targets, hosts=hosts, vlans=load_vlans())


def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _last_backups():
    """(date du dernier backup global, nb de switchs sauvegardés)."""
    files = glob.glob(os.path.join(BACKUP_DIR, "*", "*.cfg"))
    if not files:
        return None, 0
    hosts = {os.path.basename(os.path.dirname(p)) for p in files}
    latest = max(os.path.getmtime(p) for p in files)
    return datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M"), len(hosts)


@app.route("/dashboard")
@login_required
def dashboard():
    total = len(load_switch_hosts())

    # --- Firmware (dernier scan) ---
    images = [os.path.basename(p)
              for p in glob.glob(os.path.join(FIRMWARE_IMAGES_DIR, "*.swi"))]
    target = max((swi_to_version(i) for i in images), default=None)
    fw = _read_json(FIRMWARE_STATUS_JSON, [])
    fw_ok = fw_old = fw_unknown = 0
    for d in fw:
        cur = (d.get("version") or "?").strip()
        if not target or cur in ("", "?"):
            fw_unknown += 1
        elif cur == target:
            fw_ok += 1
        else:
            fw_old += 1

    # --- Conformité (dernier audit) ---
    audit = _read_json("/backups/audit.json", [])
    checks = ["ntp", "logging", "snmp_overall", "web_mgmt", "authmgr", "portsec"]
    conf_ok = 0
    for d in audit:
        d["snmp_overall"] = bool(d.get("snmp")) and bool(d.get("snmp_public"))
        if all(d.get(c) for c in checks):
            conf_ok += 1

    last_backup, n_backed = _last_backups()

    return render_template(
        "dashboard.html",
        total=total,
        fw_ok=fw_ok, fw_old=fw_old, fw_unknown=fw_unknown,
        fw_scanned=bool(fw), fw_target=target,
        conf_ok=conf_ok, conf_total=len(audit), conf_scanned=bool(audit),
        last_backup=last_backup, n_backed=n_backed,
        history=load_history()[:8],
    )


@app.route("/history")
@login_required
def history():
    return render_template("history.html", history=load_history(),
                           accounts=bool(load_users()))


@app.route("/restore")
@login_required
def restore_page():
    return render_template("restore.html", backups=load_host_backups())


def parse_trunks(text):
    """Groupes d'agrégation depuis 'show trunks' -> [{name, ports:[...]}]."""
    groups = {}
    for m in re.finditer(r"(?m)^\s*(\d[\w/]*)\s*\|.*\b(Trk\d+)\b", text or ""):
        groups.setdefault(m.group(2), []).append(m.group(1))
    return [{"name": trk, "ports": ports} for trk, ports in sorted(groups.items())]


def parse_lldp_detail(out):
    """(nom_du_voisin, port_distant) depuis 'show lldp info remote-device <port>'."""
    name = re.search(r"(?im)^\s*SysName\s*:\s*(\S.*)$", out or "")
    rport = re.search(r"(?im)^\s*PortId\s*:\s*(\S+)", out or "")
    return ((name.group(1).strip() if name else ""),
            (rport.group(1).strip() if rport else ""))


def _looks_like_mac(s):
    return bool(re.fullmatch(r"(?:[0-9A-Fa-f]{2}[\s:.-]?){6}", (s or "").strip()))


def parse_cdp(text):
    """{port_local: {device_id, ip, rport}} depuis 'show cdp neighbors detail'."""
    out = {}
    for blk in re.split(r"(?m)^-{3,}\s*$", text or ""):
        port = re.search(r"(?im)^\s*Port\s*:\s*(\S+)", blk)
        if not port:
            continue
        did = re.search(r"(?im)^\s*Device ID\s*:\s*(.+?)\s*$", blk)
        ip = re.search(r"(?im)^\s*Address\s*:\s*(\d{1,3}(?:\.\d{1,3}){3})", blk)
        rport = re.search(r"(?im)^\s*Device Port\s*:\s*(.+?)\s*$", blk)
        out[port.group(1)] = {
            "device_id": (did.group(1).strip() if did else ""),
            "ip": (ip.group(1) if ip else ""),
            "rport": (rport.group(1).strip() if rport else ""),
        }
    return out


def parse_members(*texts):
    """(dans_un_stack, [{id, role}]) depuis 'show stacking' et/ou 'show vsf'.

    Un membre = une ligne « <id> <mac>  <modèle> ... <rôle> ». Marche pour le
    backplane stacking (3810M/5400) comme pour le VSF (2920/2930)."""
    text = "\n".join(t or "" for t in texts)
    members = []
    seen = set()
    for m in re.finditer(
            r"(?m)^\s*(\d+)\s+[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}\b(.*)$", text):
        mid = m.group(1)
        if mid in seen:
            continue
        seen.add(mid)
        role = re.search(r"(Commander|Standby|Member|Active)", m.group(2))
        members.append({"id": mid, "role": role.group(1) if role else ""})
    members.sort(key=lambda x: int(x["id"]))
    return (len(members) > 0), members


@app.route("/trunks")
@login_required
def trunks_dashboard():
    data = _read_json("/backups/trunks.json", [])
    ip2name = {h["ip"]: h["name"] for h in load_switch_hosts() if h.get("ip")}
    rows = []
    for d in data:
        in_stack, members = parse_members(d.get("stacking", ""), d.get("vsf", ""))
        cdp = parse_cdp(d.get("cdp", ""))
        # Repli LLDP par port local.
        lmap = {}
        for e in d.get("lldp", []):
            nm, rp = parse_lldp_detail(e.get("out", ""))
            lmap[str(e.get("port"))] = {"neighbor": nm, "rport": rp}
        trunks = parse_trunks(d.get("trunks", ""))
        for t in trunks:
            links = []
            for p in t["ports"]:
                c = cdp.get(p, {})
                # CDP : résout le switch par son IP dans l'inventaire si possible.
                name = ip2name.get(c.get("ip", ""), "") or c.get("device_id", "")
                rport = c.get("rport", "")
                # Repli LLDP si CDP n'a pas de nom exploitable (MAC / vide).
                if not name or _looks_like_mac(name):
                    lf = lmap.get(p, {})
                    name = lf.get("neighbor", "") or name
                    rport = lf.get("rport", "") or rport
                if _looks_like_mac(rport):
                    rport = ""
                links.append({"port": p, "neighbor": name, "rport": rport})
            t["links"] = links
        rows.append({"host": d.get("host", "?"), "ip": d.get("ip", ""),
                     "in_stack": in_stack, "members": members, "trunks": trunks})
    rows.sort(key=lambda r: r["host"])
    return render_template("trunks.html", rows=rows, scanned=bool(data))


@app.route("/sync_librenms", methods=["POST"])
@login_required
def sync_librenms():
    """Régénère inventory/hosts.yml depuis LibreNMS (auto-détection vendor)."""
    run_id = uuid.uuid4().hex
    RUNS[run_id] = {"q": queue.Queue(), "done": False}
    cmd = ["python", "inventory/from_librenms.py", "inventory/hosts.yml"]
    log_history_start(run_id, session.get("who"), client_ip(),
                      "Synchroniser LibreNMS", "inventaire", "")
    threading.Thread(target=run_job, args=(run_id, cmd), daemon=True).start()
    return render_template("run.html", run_id=run_id,
                           action="Synchroniser l'inventaire (LibreNMS)",
                           back=url_for("dashboard"), auto_redirect=False)


BASELINE_TOGGLES = ("baseline_ntp", "baseline_logging", "baseline_snmp",
                    "baseline_web_mgmt_off", "baseline_authmgr",
                    "baseline_banner",
                    "baseline_spanning_tree", "baseline_loop_protect")
BASELINE_TEXT = ("ntp_server", "logging_server", "snmp_community",
                 "snmp_contact", "authorized_manager", "banner_motd")


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    saved = False
    if request.method == "POST":
        data = {k: request.form.get(k, "").strip() for k in BASELINE_TEXT}
        # Communautés SNMP : lignes parallèles nom/accès.
        names = request.form.getlist("snmp_comm_name")
        accesses = request.form.getlist("snmp_comm_access")
        comms = []
        for n, a in zip(names, accesses):
            n = n.strip()
            if n:
                comms.append({"name": n,
                              "access": a if a in ("restricted", "operator",
                                                   "manager", "unrestricted")
                              else "restricted"})
        data["snmp_communities"] = comms
        data["snmp_remove_communities"] = [
            t.strip() for t in re.split(r"[,\n\r]+",
                                        request.form.get("snmp_remove_communities", ""))
            if t.strip()]
        # On n'utilise plus le champ unique : on le vide pour éviter la migration.
        data["snmp_community"] = ""
        # VLAN protégés : liste d'entiers depuis une saisie « 10, 20, 61 ».
        vlans = []
        for tok in re.split(r"[,\s]+", request.form.get("protected_vlans", "")):
            if tok.isdigit():
                vlans.append(int(tok))
        data["protected_vlans"] = vlans
        try:
            data["loop_protect_disable_timer"] = int(
                request.form.get("loop_protect_disable_timer", "300"))
        except ValueError:
            data["loop_protect_disable_timer"] = 300
        # Cases cochées = présentes dans le formulaire.
        for t in BASELINE_TOGGLES:
            data[t] = bool(request.form.get(t))
        save_baseline(data)
        saved = True
    cfg = load_baseline()
    cfg["protected_vlans_str"] = ", ".join(str(v) for v in cfg.get("protected_vlans", []))
    return render_template("settings.html", cfg=cfg, saved=saved)


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
        # Réglages éditables dans la page « Config standard » (baseline.json).
        extra.update(load_baseline())
        extra["baseline_dry_run"] = bool(form.get("baseline_dry_run"))
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
    if action == "restore":
        extra.update({
            "restore_file": form.get("restore_file", ""),
            "restore_dry_run": bool(form.get("restore_dry_run")),
            "restore_tftp_server": os.environ.get("TFTP_SERVER", ""),
        })
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
        log_history_finish(run_id, proc.returncode)
    except Exception as exc:  # noqa: BLE001
        q.put(f"\n[ERREUR lancement] {exc}\n")
        log_history_finish(run_id, -1)
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
    # Journalise l'action (sauf la collecte silencieuse des VLANs pour le menu).
    if action != "vlan_list":
        log_history_start(run_id, session.get("who"), client_ip(),
                          ACTIONS[action]["label"],
                          request.form.get("target", "procurve"),
                          action_summary(action, request.form))
    threading.Thread(target=run_job, args=(run_id, cmd), daemon=True).start()
    # Après une collecte (versions / VLANs), on revient automatiquement à la page.
    if action == "firmware_status":
        back = url_for("firmware_dashboard")
    elif action == "audit":
        back = url_for("audit_dashboard")
    elif action == "cmd":
        back = url_for("console_result")
    elif action == "restore":
        back = url_for("restore_page")
    elif action == "trunks":
        back = url_for("trunks_dashboard")
    else:
        back = url_for("index")
    return render_template("run.html", run_id=run_id,
                           action=ACTIONS[action]["label"], back=back,
                           auto_redirect=(action in ("firmware_status", "vlan_list",
                                                     "audit", "cmd", "trunks")))


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
