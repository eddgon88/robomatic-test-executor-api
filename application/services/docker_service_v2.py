from typing import Tuple
import docker
import time
import os
import logging
import requests
from docker.errors import DockerException, NotFound

# --- CONFIGURACIÓN ---
# El logging se configura en el módulo principal que usa este servicio.
# Es buena práctica que las librerías/módulos secundarios no configuren el logging global.

class DockerService:
    """
    Gestiona el ciclo de vida de los contenedores de Docker para las pruebas de Selenium.
    Cada instancia de esta clase tiene su propio cliente de Docker.
    """
    def __init__(self):
        """
        Inicializa el cliente de Docker y verifica la conexión.
        """
        try:
            self.client = docker.from_env()
            self.client.ping()
            logging.info("DockerService instance created and connected to Docker daemon.")
        except DockerException as e:
            logging.error(f"Could not connect to Docker daemon. Is it running? Error: {e}")
            # Levanta la excepción para que el servicio que lo instancia sepa que no puede continuar.
            raise

    def _clean_dead_containers(self):
        """
        Elimina contenedores en estado 'exited' para liberar recursos, especialmente puertos.
        """
        try:
            exited_containers = self.client.containers.list(all=True, filters={'status': 'exited'})
            if not exited_containers:
                return

            logging.info(f"Found {len(exited_containers)} dead containers. Cleaning up...")
            for container in exited_containers:
                try:
                    logging.info(f"Removing dead container: {container.name} (ID: {container.id})")
                    container.remove()
                except DockerException as e:
                    logging.error(f"Failed to remove dead container {container.name}: {e}")
        except DockerException as e:
            logging.error(f"Error while trying to list dead containers: {e}")

    def _find_available_ports(self, base_selenium_port=4444, base_vnc_port=5900, range_limit=20) -> Tuple[int, int]:
        """
        Encuentra un par de puertos (Selenium, VNC) que no estén actualmente en uso por otros contenedores.
        """
        occupied_ports = set()
        for container in self.client.containers.list():
            try:
                ports = container.attrs['NetworkSettings']['Ports']
                for port_mapping in ports.values():
                    if port_mapping:
                        for mapping in port_mapping:
                            if mapping.get('HostPort'):
                                occupied_ports.add(int(mapping['HostPort']))
            except (KeyError, TypeError):
                continue
        
        for i in range(range_limit):
            selenium_port = base_selenium_port + i
            vnc_port = base_vnc_port + i
            if selenium_port not in occupied_ports and vnc_port not in occupied_ports:
                logging.info(f"Found available ports: Selenium={selenium_port}, VNC={vnc_port}")
                return selenium_port, vnc_port

        raise RuntimeError(f"Could not find available ports in the range {base_selenium_port}-{base_selenium_port + range_limit}")

    def _wait_for_selenium_ready(self, container: str, port: int, timeout: int = 45):
        """
        Espera activamente a que el hub de Selenium esté listo para recibir conexiones.
        Esto es mucho más fiable que un time.sleep().
        """
        time.sleep(5)  # Esperar a que el contenedor se inicialice
        container.reload()
        start_time = time.time()
        logging.info(f"Waiting for Selenium to be ready at port {port}...")
        
        while time.time() - start_time < timeout:
            try:
                status = container.attrs['State']
                if status['Running']:
                    logging.info(f"Selenium at port {port} is ready!")
                    return
                else:
                    logging.info(f"Selenium at port {port} is not running yet. Current status: {status['Status']}")
                    time.sleep(1)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                # Es normal obtener errores de conexión mientras el servidor se inicia
                time.sleep(1)
            except Exception as e:
                logging.warning(f"Unexpected error while polling Selenium status: {e}")
                time.sleep(1)
                
        raise TimeoutError(f"Selenium at port {port} was not ready within {timeout} seconds.")

    def create_selenium_container(self) -> Tuple[Tuple[int, int], 'docker.models.containers.Container']:
        """
        Orquesta la creación de un contenedor de Selenium: limpia, busca puertos, lo crea y espera a que esté listo.
        
        Returns:
            Una tupla que contiene:
            - Una tupla con los puertos asignados (selenium_port, vnc_port).
            - El objeto contenedor de Docker.
        """
        self._clean_dead_containers()
        
        selenium_port, vnc_port = self._find_available_ports()
        
        container_name = f'selenium_vnc_{selenium_port}_{vnc_port}'
        image_name = os.getenv('SELENIUM_IMAGE', 'selenium/standalone-chrome:latest')
        network_name = 'robomatic-docker-compose_robomatic-net'

        container_config = {
            'image': image_name,
            'detach': True,
            'ports': {'4444/tcp': selenium_port, '5900/tcp': vnc_port},
            'name': container_name,
            'network': network_name,
            'mem_limit': os.getenv('DOCKER_MEM_LIMIT', '2g'),
            # Añadir shm_size puede solucionar problemas de 'crasheo' del navegador dentro del contenedor
            'shm_size': '2g' 
        }

        try:
            logging.info(f"Creating container '{container_name}' from image '{image_name}'...")
            container = self.client.containers.run(**container_config)
            
            self._wait_for_selenium_ready(container, selenium_port)

            return (selenium_port, vnc_port), container
        except DockerException as e:
            logging.error(f"Failed to create Docker container: {e}")
            raise

    def destroy_container(self, container_name: str):
        """
        Detiene y elimina un contenedor de forma segura por su nombre.
        """
        try:
            logging.info(f"Attempting to destroy container '{container_name}'...")
            container = self.client.containers.get(container_name)
            container.stop()
            container.remove()
            logging.info(f"Container '{container_name}' destroyed successfully.")
        except NotFound:
            logging.warning(f"Container '{container_name}' not found for destruction. It might have been already removed.")
        except DockerException as e:
            logging.error(f"An error occurred while destroying container '{container_name}': {e}")

    def create_docker_image(self):
        self.client.images.build(
            path    = os.getenv('RESOURCES_DIR'),
            tag     = os.getenv('SELENIUM_IMAGE'),
            rm      = True,           # Eliminar contenedores intermedios después de la construcción
            pull    = True,         # Intentar obtener una versión más reciente de la imagen base
            forcerm = True     # Forzar la eliminación de contenedores intermedios si falla la construcción
        )
    