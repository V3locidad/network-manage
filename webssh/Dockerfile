# Terminal SSH web (xterm) — paquet PyPI « webssh » (commande wssh).
FROM python:3.12-slim

RUN pip install --no-cache-dir webssh

# Réactivation des algorithmes SSH legacy (switchs anciens) — auto-importé.
COPY sitecustomize.py /opt/sshcompat/sitecustomize.py
ENV PYTHONPATH=/opt/sshcompat

EXPOSE 8888

CMD ["wssh", "--address=0.0.0.0", "--port=8888"]
