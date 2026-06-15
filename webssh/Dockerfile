# Terminal SSH web (xterm) — paquet PyPI « webssh » (commande wssh).
FROM python:3.12-slim

# paramiko épinglé en 3.5.x : les versions 4.x/5.x ont retiré les algorithmes
# SSH SHA1 nécessaires aux vieux switchs (cf. sitecustomize.py).
RUN pip install --no-cache-dir webssh 'paramiko>=3.5,<4.0'

# Réactivation des algorithmes SSH legacy (switchs anciens) — auto-importé.
COPY sitecustomize.py /opt/sshcompat/sitecustomize.py
ENV PYTHONPATH=/opt/sshcompat

EXPOSE 8888

CMD ["wssh", "--address=0.0.0.0", "--port=8888"]
