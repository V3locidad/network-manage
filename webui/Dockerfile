# Interface web maison + Ansible, dans une seule image légère.
FROM python:3.12-slim

# Collections installées dans un chemin système (indépendant du HOME runtime).
ENV ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssh-client sshpass \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Collections réseau (mêmes que le projet) intégrées à l'image.
RUN ansible-galaxy collection install -p /usr/share/ansible/collections \
      cisco.ios cisco.nxos arubanetworks.aoscx arubanetworks.aos_switch ansible.netcommon

COPY app.py /app/app.py
COPY templates /app/templates
WORKDIR /app

EXPOSE 8080
CMD ["python", "app.py"]
