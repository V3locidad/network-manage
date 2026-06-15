# Serveur TFTP minimal pour héberger les images firmware (.swi) des switchs.
FROM debian:12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tftpd-hpa \
 && rm -rf /var/lib/apt/lists/*

EXPOSE 69/udp

# Sert /srv/tftp en lecture seule, en avant-plan (pour le conteneur).
CMD ["/usr/sbin/in.tftpd", "--foreground", "--user", "tftp", \
     "--address", "0.0.0.0:69", "--secure", "/srv/tftp"]
