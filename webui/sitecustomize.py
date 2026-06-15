"""Réactive les algorithmes SSH « legacy » dans paramiko.

Les switchs anciens (Aruba/HP ProCurve, vieux Cisco IOS) ne proposent souvent
que des algorithmes SHA1 / Diffie-Hellman group1/14 que les versions récentes
de paramiko désactivent par défaut -> « no acceptable kex algorithm ».

Ce module est importé automatiquement par Python au démarrage (sitecustomize),
donc il s'applique aussi bien à WebSSH qu'aux connexions Ansible network_cli.
"""
try:
    from paramiko.transport import Transport

    def _add(attr, extra):
        cur = list(getattr(Transport, attr, ()))
        for algo in extra:
            if algo not in cur:
                cur.append(algo)
        setattr(Transport, attr, tuple(cur))

    _add("_preferred_kex", (
        "diffie-hellman-group-exchange-sha1",
        "diffie-hellman-group14-sha1",
        "diffie-hellman-group1-sha1",
    ))
    _add("_preferred_keys", (
        "ssh-rsa",
    ))
    _add("_preferred_ciphers", (
        "aes128-cbc", "aes256-cbc", "3des-cbc",
    ))
    _add("_preferred_macs", (
        "hmac-sha1", "hmac-sha1-96",
    ))
except Exception:
    # Pas de paramiko / API changée : on n'empêche surtout pas le démarrage.
    pass
