import docker
import time
import os
import logging
from docker.errors import DockerException

logging.basicConfig(level=logging.INFO,
                    format='(%(threadName)-10s) %(message)s',)

client = docker.from_env()
dockerfile_path = os.getenv('RESOURCES_DIR')  # Ruta absoluta al Dockerfile
image_name = os.getenv('SELENIUM_IMAGE')
ports = [4444, 5900, 4449]


class DockerService:
    @staticmethod
    def createDockerImage():
        image = client.images.build(
            path    = os.getenv('RESOURCES_DIR'),
            tag     = os.getenv('SELENIUM_IMAGE'),
            rm      = True,           # Eliminar contenedores intermedios después de la construcción
            pull    = True,         # Intentar obtener una versión más reciente de la imagen base
            forcerm = True     # Forzar la eliminación de contenedores intermedios si falla la construcción
        )
    
    #@staticmethod
    #def createDocker():
    #    ret_ports = check_ports()
#
    #    container_config = {
    #        'image': os.getenv('SELENIUM_IMAGE'),  # Nombre de la imagen Docker
    #        'detach': True,  # Ejecución en segundo plano
    #        'ports': {'4444/tcp': str(ret_ports[0]), '5900/tcp': str(ret_ports[1])},  # Mapeo de puertos (puerto_contenedor/tcp: puerto_host)
    #        'name': 'selenium_vnc_' + str(ret_ports[0]) + '_' + str(ret_ports[1])  # Nombre para el contenedor
    #    }
#
    #    cont = client.containers.run(**container_config)
    #    #cont.reload()
    #    time.sleep(3)
#
    #    network = client.networks.get('robomatic-docker-compose_robomatic-net')
    #    #network.reload()
    #    connected_containers = [c.name for c in network.containers]
    #    if container_config['name'] not in connected_containers:
    #        print(f"Conectando contenedor {container_config['name']} a la red...")
    #        network.connect(cont)
    #        time.sleep(1)
#
    #    return ret_ports, cont
    
    @staticmethod
    def createDocker():
        """
        Crea un contenedor Docker para Selenium con puertos asignados.
        
        Args:
            client: Cliente Docker.
        
        Returns:
            Tuple[tuple, Container]: Puertos asignados y objeto contenedor.
        """
        try:
            ret_ports = check_ports(client)
            
            container_config = {
                'image': os.getenv('SELENIUM_IMAGE', 'selenium/standalone-chrome:latest'),
                'detach': True,
                'ports': {'4444/tcp': str(ret_ports[0]), '5900/tcp': str(ret_ports[1])},
                'name': f'selenium_vnc_{ret_ports[0]}_{ret_ports[1]}',
                'network': 'robomatic-docker-compose_robomatic-net',  # Conectar directamente a la red
                'mem_limit': '2g',
            }

            logging.info(f"Iniciando contenedor con config: {container_config}")
            cont = client.containers.run(**container_config)
            logging.info(f"Contenedor {container_config['name']} creado con ID: {cont.id}")

            time.sleep(5)  # Esperar a que el contenedor se inicialice
            cont.reload()
            status = cont.attrs['State']
            if not status['Running']:
                logs = cont.logs().decode('utf-8')
                logging.error(f"El contenedor no está corriendo. Estado: {status}, Logs: {logs}")
                raise RuntimeError(f"Contenedor {container_config['name']} no está corriendo")

            return ret_ports, cont
        
        except DockerException as e:
            logging.error(f"Error de Docker al crear contenedor: {str(e)}")
            raise
        except Exception as e:
            logging.error(f"Error inesperado al crear contenedor: {str(e)}")
            raise

    @staticmethod
    def docker_image():
        images = client.images.list()
        print(images)

    @staticmethod
    def docker_ps():
        dockers = client.containers.list()
        print(dockers)

    @staticmethod
    def destroy_docker(name: str):
        container = client.containers.get(name)
        container.kill()  # Mata el contenedor
        container.remove()  # Elimina el contenedor
    
#def check_ports():
#    global ports
#    selenium_port = ports[0]
#    vnc_port = ports[1]
#    ret_ports = (selenium_port, vnc_port)
#    limit = ports[2]
#    dockers = client.containers.list()
#    for docker in dockers:
#        dports = docker.attrs['NetworkSettings']['Ports']
#        for host_ports in dports.items():
#            for host_port in host_ports:
#                if host_port is not None:
#                    #print(f"  Mapeado al puerto del host: {host_port}")
#                    if host_port == str(selenium_port)+'/tcp' :
#                        selenium_port +=1
#                        vnc_port +=1
#                        ret_ports = (selenium_port, vnc_port)
#            if selenium_port > limit:
#                time.sleep(60)
#                ret_ports = check_ports()
#    return ret_ports

def check_ports(client, base_selenium_port=4444, base_vnc_port=5900, port_limit=4454, max_attempts=5):
    """
    Verifica y asigna puertos disponibles para Selenium y VNC.
    
    Args:
        client: Cliente Docker.
        base_selenium_port: Puerto base para Selenium.
        base_vnc_port: Puerto base para VNC.
        port_limit: Límite superior para los puertos.
        max_attempts: Número máximo de intentos para encontrar puertos disponibles.
    
    Returns:
        Tuple[int, int]: Puertos disponibles para Selenium y VNC.
    """
    try:
        # Limpiar contenedores muertos primero
        clean_dead_containers(client)
        
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            selenium_port = base_selenium_port
            vnc_port = base_vnc_port
            
            # Obtener puertos ocupados
            logging.info("Verificando puertos ocupados...")
            occupied_ports = set()
            containers = client.containers.list()
            for container in containers:
                ports = container.attrs['NetworkSettings']['Ports']
                for port_mapping in ports.values():
                    if port_mapping:  # Puede ser None si el puerto no está mapeado
                        for mapping in port_mapping:
                            host_port = mapping.get('HostPort')
                            if host_port:
                                occupied_ports.add(int(host_port))
            
            # Intentar encontrar puertos libres
            while selenium_port <= port_limit:
                if selenium_port not in occupied_ports and vnc_port not in occupied_ports:
                    logging.info(f"Puertos asignados: Selenium={selenium_port}, VNC={vnc_port}")
                    return selenium_port, vnc_port
                
                selenium_port += 1
                vnc_port += 1
            
            logging.warning(f"No se encontraron puertos libres en el intento {attempt}/{max_attempts}. Esperando...")
            time.sleep(10)  # Esperar antes de reintentar
        
        raise RuntimeError(f"No se encontraron puertos disponibles tras {max_attempts} intentos.")
    
    except DockerException as e:
        logging.error(f"Error de Docker al verificar puertos: {str(e)}")
        raise
    except Exception as e:
        logging.error(f"Error inesperado al verificar puertos: {str(e)}")
        raise

def clean_dead_containers(client):
    """
    Elimina contenedores en estado 'exited' para liberar puertos.
    """
    try:
        logging.info("Verificando contenedores muertos...")
        containers = client.containers.list(all=True)  # Incluye contenedores detenidos
        dead_containers = [c for c in containers if c.status == 'exited']
        
        if not dead_containers:
            logging.info("No se encontraron contenedores muertos.")
            return
        
        for container in dead_containers:
            try:
                logging.info(f"Eliminando contenedor muerto: {container.name} (ID: {container.id})")
                container.remove(force=True)  # force=True para eliminar incluso si está detenido
            except DockerException as e:
                logging.error(f"Error al eliminar contenedor {container.name}: {str(e)}")
        
        logging.info(f"Eliminados {len(dead_containers)} contenedores muertos.")
    except DockerException as e:
        logging.error(f"Error al listar contenedores muertos: {str(e)}")
        raise
    except Exception as e:
        logging.error(f"Error inesperado al limpiar contenedores muertos: {str(e)}")
        raise
