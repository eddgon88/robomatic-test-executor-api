import docker
import time
import os

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
    
    @staticmethod
    def createDocker():
        ret_ports = check_ports()

        container_config = {
            'image': os.getenv('SELENIUM_IMAGE'),  # Nombre de la imagen Docker
            'detach': True,  # Ejecución en segundo plano
            'ports': {'4444/tcp': str(ret_ports[0]), '5900/tcp': str(ret_ports[1])},  # Mapeo de puertos (puerto_contenedor/tcp: puerto_host)
            'name': 'selenium_vnc_' + str(ret_ports[0]) + '_' + str(ret_ports[1])  # Nombre para el contenedor
        }

        cont = client.containers.run(**container_config)
        network = client.networks.get('robomatic-docker-compose_robomatic-net')
        network.connect(cont)

        return ret_ports, cont

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
    
def check_ports():
    global ports
    selenium_port = ports[0]
    vnc_port = ports[1]
    ret_ports = (selenium_port, vnc_port)
    limit = ports[2]
    dockers = client.containers.list()
    for docker in dockers:
        dports = docker.attrs['NetworkSettings']['Ports']
        for host_ports in dports.items():
            for host_port in host_ports:
                if host_port is not None:
                    #print(f"  Mapeado al puerto del host: {host_port}")
                    if host_port == str(selenium_port)+'/tcp' :
                        selenium_port +=1
                        vnc_port +=1
                        ret_ports = (selenium_port, vnc_port)
            if selenium_port > limit:
                time.sleep(60)
                ret_ports = check_ports()
    return ret_ports
