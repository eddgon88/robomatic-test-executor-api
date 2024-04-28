#!/bin/bash

# Iniciar el servidor Xvfb
Xvfb :99 -ac -screen 0 1280x1024x16 &

# Iniciar fluxbox (entorno gráfico)
fluxbox &

# Iniciar x11vnc (servidor VNC)
x11vnc -display :99 -nopw -listen 0.0.0.0 -xkb -ncache 10 -ncache_cr -forever &

# Iniciar Selenium Grid
#java -Dwebdriver.chrome.driver=/usr/bin/chromedriver -jar /opt/selenium/selenium-server-standalone.jar -role hub &
#java -Dwebdriver.chrome.driver=/usr/bin/chromedriver -jar /opt/selenium/selenium-server-standalone.jar -role node -hub http://localhost:4444/grid/register -browser "browserName=chrome,maxInstances=5" &
#sleep infinity

#==============================================
# OpenShift or non-sudo environments support
# https://docs.openshift.com/container-platform/3.11/creating_images/guidelines.html#openshift-specific-guidelines
#==============================================

if ! whoami &> /dev/null; then
  if [ -w /etc/passwd ]; then
    echo "${USER_NAME:-default}:x:$(id -u):0:${USER_NAME:-default} user:${HOME}:/sbin/nologin" >> /etc/passwd
  fi
fi

/usr/bin/supervisord --configuration /etc/supervisord.conf &

SUPERVISOR_PID=$!

function shutdown {
    echo "Trapped SIGTERM/SIGINT/x so shutting down supervisord..."
    kill -s SIGTERM ${SUPERVISOR_PID}
    wait ${SUPERVISOR_PID}
    echo "Shutdown complete"
}

trap shutdown SIGTERM SIGINT
wait ${SUPERVISOR_PID}

