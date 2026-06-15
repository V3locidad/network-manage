"""Réactive les algorithmes SSH « legacy » dans paramiko.

Les switchs anciens (Aruba/HP ProCurve, vieux Cisco IOS) ne proposent souvent
que des algorithmes SHA1 / Diffie-Hellman group1/14 que les versions récentes
de paramiko désactivent par défaut -> « no acceptable kex algorithm ».

⚠ Il ne suffit PAS de les remettre dans la liste des préférés : paramiko 3.x a
aussi retiré leur implémentation du dico `_kex_info`, donc une fois l'algo
choisi on obtient une `KeyError`. On ré-enregistre donc les classes elles-mêmes.

Ce module est importé automatiquement par Python au démarrage (sitecustomize),
donc il s'applique aussi bien à WebSSH qu'aux connexions Ansible network_cli.
"""
try:
    from paramiko.transport import Transport

    # 1) Ré-enregistrer les implémentations KEX legacy dans _kex_info.
    kex_info = getattr(Transport, "_kex_info", {})
    try:
        from paramiko.kex_group1 import KexGroup1
        kex_info.setdefault("diffie-hellman-group1-sha1", KexGroup1)
    except Exception:
        pass
    try:
        from paramiko.kex_group14 import KexGroup14
        kex_info.setdefault("diffie-hellman-group14-sha1", KexGroup14)
    except Exception:
        pass
    try:
        from paramiko.kex_gex import KexGex
        kex_info.setdefault("diffie-hellman-group-exchange-sha1", KexGex)
    except Exception:
        pass

    def _add(attr, names, registry=None):
        """Ajoute `names` à la liste `attr` — seulement ceux réellement
        implémentés (présents dans `registry`) pour éviter toute KeyError."""
        cur = list(getattr(Transport, attr, ()))
        for n in names:
            if registry is not None and n not in registry:
                continue
            if n not in cur:
                cur.append(n)
        setattr(Transport, attr, tuple(cur))

    _add("_preferred_kex", (
        "diffie-hellman-group-exchange-sha1",
        "diffie-hellman-group14-sha1",
        "diffie-hellman-group1-sha1",
    ), registry=kex_info)
    _add("_preferred_keys", ("ssh-rsa",),
         registry=getattr(Transport, "_key_info", None))
    _add("_preferred_ciphers", ("aes128-cbc", "aes256-cbc", "3des-cbc"),
         registry=getattr(Transport, "_cipher_info", None))
    _add("_preferred_macs", ("hmac-sha1", "hmac-sha1-96"),
         registry=getattr(Transport, "_mac_info", None))
except Exception:
    # Pas de paramiko / API changée : on n'empêche surtout pas le démarrage.
    pass
