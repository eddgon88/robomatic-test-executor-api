# Imagen base con Chrome, VNC, y Java
FROM selenium/standalone-chrome:latest
#docker pull selenium/standalone-chrome:latest
# Instalar VNC Server
RUN sudo apt-get update && sudo apt-get install -y x11vnc xvfb fluxbox wmctrl && \
    sudo apt-get clean && \
    sudo rm -rf /var/lib/apt/lists/*

# Configurar el contenedor para el servidor VNC
COPY entrypoint.sh /
#RUN chmod +x /entrypoint.sh

EXPOSE 4444 5900

ENTRYPOINT ["sh", "-c", "/entrypoint.sh"]
