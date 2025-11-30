import pandas
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from .. import utils
from sqlalchemy import text, create_engine
from datetime import datetime, timedelta
import time
import os
import logging
import pika
import requests
import json
from bs4 import BeautifulSoup
from xml.dom import minidom
from selenium import webdriver
from selenium.webdriver.common.by import By
from ..services.docker_service_v2 import DockerService # Asumido
from dotenv import load_dotenv

# --- CONFIGURACIÓN ---
logging.basicConfig(level=logging.INFO,
                    format='(%(threadName)-10s) [%(levelname)s] %(message)s',)
load_dotenv()
# La conexión a la BD se puede gestionar por instancia o globalmente si el pool es thread-safe
# engine = create_engine(os.getenv('DB_SERVER_URL'))

# --- CLASE REFACTORIZADA ---
class TestExecutorService:
    def __init__(self, execute_object: dict):
        """
        Constructor que inicializa el estado para UNA SOLA ejecución de prueba.
        """
        self.config = execute_object
        self.test_execution_id = self.config['test_execution_id']
        
        # Atributos de estado específicos de esta instancia
        self.driver = None
        self.container = None
        self.docker_service = DockerService()
        self.engine = create_engine(os.getenv('DB_SERVER_URL'))

        # Datos de ejecución, ahora como atributos de instancia
        self.test_execution_data = {
            'test_execution_id': self.test_execution_id,
            'status': 'success' # Inicia como success, cambia si algo falla
        }
        self.case_execution_data = {}

        # Mapeo de selectores de Selenium
        self.BY_MAP = {
            "xpath": By.XPATH,
            "id": By.ID,
            "name": By.NAME,
            "class_name": By.CLASS_NAME,
            "css_selector": By.CSS_SELECTOR,
            "link_text": By.LINK_TEXT,
            "partial_link_text": By.PARTIAL_LINK_TEXT,
            "tag_name": By.TAG_NAME
        }
        logging.info(f"Instancia TestExecutorService creada para ejecución {self.test_execution_id}")

    def _create_environment(self):
        """Crea el contenedor de Docker y la instancia de WebDriver."""
        if not self.config.get('web'):
            return

        logging.info("Creando entorno web...")
        # Recomiendo usar la versión mejorada de DockerService que espera a que el hub esté listo
        ports, self.container = self.docker_service.create_selenium_container()
        selenium_port, vnc_port = ports # Estos son los puertos en localhost
        logging.info(f"Contenedor creado: {self.container.name} con puertos {ports}")
        
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-notifications")
        options.add_argument("--start-maximized")
        options.add_experimental_option("prefs", {
                "profile.default_content_setting_values.notifications": 2  # 2 = bloquear
            })
        # options.add_argument("--headless") # Considerar para ejecuciones en servidor

        command_executor_url = f'http://{self.container.name}:4444'
        logging.info(f"Connecting WebDriver to {command_executor_url}...")

        time.sleep(10)
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                self.driver = webdriver.Remote(
                    command_executor=command_executor_url,
                    options=options
                )
                logging.info(f"WebDriver conectado exitosamente para la ejecución {self.test_execution_id}")
                break
            except Exception as e:
                logging.warning(f"Intento fallido: {str(e)}")
                if attempt == max_attempts - 1:
                    self.docker_service.destroy_container(str(self.container.name))
                    raise Exception(f"No se pudo conectar a Selenium tras {max_attempts} intentos: {str(e)}")
                time.sleep(5)
        logging.info(f"WebDriver conectado para {self.test_execution_id}")
        
        with self.engine.connect() as connection:
                try:
                    trans = connection.begin()
                    webquery = text("""
                        INSERT INTO test_executor.test_port (execution_id, selenium_port, vnc_port) 
                        VALUES (:execution_id, :selenium_port, :vnc_port)
                    """)
                    
                    # Parameters to prevent SQL injection
                    params = {
                        'execution_id': self.config['test_execution_id'],
                        'selenium_port': str(selenium_port),
                        'vnc_port': str(vnc_port)
                    }
                    
                    result = connection.execute(webquery, params)
                    
                    # For INSERT operations, print the row count and primary key value (if any)
                    logging.info(f"Rows affected: {result.rowcount}")
                    logging.info(f"Last inserted ID: {result.lastrowid}")
                    trans.commit()  # Commit the transaction
                    
                except Exception as e:
                    logging.error(f"An error occurred: {e}")
                    trans.rollback() 

    def _cleanup(self):
        """Limpia los recursos: cierra el driver y destruye el contenedor."""
        logging.info(f"Iniciando limpieza para {self.test_execution_id}")
        if self.driver:
            try:
                self.driver.quit()
                logging.info("Sesión de WebDriver cerrada.")
            except Exception as e:
                logging.warning(f"Error al cerrar WebDriver: {e}")
        
        if self.container:
            self.docker_service.destroy_container(self.container.name)

    def _get_script_globals(self) -> dict:
        """
        Crea un diccionario de todas las funciones que el script de prueba puede llamar.
        Cada función "recuerda" el 'self' de esta instancia, dándole acceso a self.driver.
        ¡Esta es la clave para que los scripts no necesiten cambios!
        """
        def get(url):
            self.driver.get(url)

        def getElement(element):
            for by in self.BY_MAP:
                try:
                    return self.driver.find_element(by, element)
                except Exception as e:
                    exeption = e
                    #log
            raise Exception("Element no reachable")

        def assertion(condition, message):
            if not condition:
                self.test_execution_data['status'] = "failed"
                logging.error(f"ASSERTION FAILED: {message}")
                # Aquí podrías escribir en la evidencia, etc.
                raise AssertionError(message)
        
        def writeEvidence(fileName, content, fileType):
            query = "SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = '" + fileName + \
                ".txt' and e.test_execution_id = '" + \
                    self.test_execution_data['test_execution_id'] + "'"
            if fileType == 1:
                query = "SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = '" + fileName + \
                    ".txt' and e.test_execution_id = '" + \
                        self.test_execution_data['test_execution_id'] + "'"
            else:
                query = "SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = '" + fileName + ".txt' and e.test_execution_id = '" + \
                    self.test_execution_data['test_execution_id'] + "' AND e.case_execution_id = '" + \
                        self.case_execution_data['case_execution_id'] + "'"
            with self.engine.connect() as connection:
                result = connection.execute(text(query)).first()
            if result:
                evidence_file_id = result.evidence_id
                with self.engine.connect() as connection:
                    try:
                        trans = connection.begin()
                        date = datetime.today()
                        query = "INSERT INTO test_executor.case_evidence (evidence_id,evidence_text, creation_date) VALUES ('" + \
                            evidence_file_id+"','"+content+"', '"+str(date)+"');"
                        connection.execute(text(query))
                        trans.commit() 
                    except Exception as e:
                            logging.error(f"An error occurred: {e}")
                            trans.rollback()      
            else:
                evidence_file_id = utils.generateRandomId("ef")
                file_name = fileName + '.txt'
                if fileType == 1:
                    evidence_uri = os.getenv('EVIDENCE_FILE_DIR')+ '/' + \
                        self.test_execution_data['test_execution_id'] + \
                        '/' + fileName + '.txt'
                else:
                    evidence_uri = os.getenv('EVIDENCE_FILE_DIR')+ '/' + self.test_execution_data['test_execution_id'] + \
                        '/' + \
                        self.case_execution_data['case_execution_id'] + \
                        '/' + fileName + '.txt'
                test_execution_id = self.test_execution_data['test_execution_id']
                with self.engine.connect() as connection:
                    try:
                        trans = connection.begin()
                        query = "INSERT INTO test_executor.evidence_file (evidence_id,file_name,evidence_uri, type_id, test_execution_id, case_execution_id) VALUES ('" + \
                            evidence_file_id+"','"+file_name+"','"+evidence_uri+"'," + \
                                str(fileType)+",'"+test_execution_id+"','" + \
                            self.case_execution_data['case_execution_id']+"');"
                        connection.execute(text(query))
                        date = datetime.today()
                        query = "INSERT INTO test_executor.case_evidence (evidence_id,evidence_text, creation_date) VALUES ('" + \
                            evidence_file_id+"','"+content+"', '"+str(date)+"');"
                        connection.execute(text(query))
                        trans.commit()
                    except Exception as e:
                            logging.error(f"An error occurred: {e}")
                            trans.rollback()    

        def writeGlobalEvidence(fileName, content):
            logging.info('writing global evidence: ' + fileName)
            writeEvidence(fileName, content, 1)

        def writeCaseEvidence(fileName, content):
            logging.info('writing unitary evidence: ' + fileName)
            writeEvidence(fileName, content, 2)

        def sleep(s):
            logging.info('sleeping for ' + str(s) + ' seconds')
            time.sleep(s)
        
        def consumeService(request):
            #print(type(request))
            logging.info('calling some service ' + request['url'])
            json_request = json.dumps(request)
            r = requests.post(
                os.getenv('REST_API_URL'), data=json_request)
            return self.responseMapper(r.json(), request)
        
        def executeQuery(dbconfig):
            logging.info('executing some query ' + dbconfig['query'])
            json_request = json.dumps(dbconfig)
            r = requests.post(
                os.getenv('DATABASE_API_URL'), data=json_request)
            return r.json()
        
        def sendJmsQueue(jmsconfig):
            logging.info('sending some queue to: ' + jmsconfig['engine'])
            json_request = json.dumps(jmsconfig)
            r = requests.post(
                os.getenv('JMS_API_URL'), data=json_request)
            logging.info('sended queue: ' + str(r))
            return r.content
        
        def sendMail(mails, subject, body, files, template_id):
            logging.info('sending mail')
            mail_array = mails.split(',')
            if str(type(body)) == "<class 'str'>":
                body_dict = None
                template_id = None
                body_str = body
            else:
                body_dict = body
                body_str = ""
            file_array = files.split(',')
            message = {
                "email": mail_array,
                "subject": subject,
                "execution_id": self.test_execution_data['test_execution_id'],
                "body": body_str,
                "body_dict": body_dict,
                "template_id": template_id,
                "files": file_array
            }
            req = json.dumps(message)
            r = requests.post(
                os.getenv('MAIL_API_URL'), data=req)
            logging.info('Mail sended')

        def getGsheet(request):
            print(type(request))
            logging.info('calling some gsheet ' + request['file_id'])
            json_request = json.dumps(request)
            r = requests.post(
                os.getenv("GDRIVE_API_URL"), data=json_request)
            return self.defaultResponseMapper(r.json(), request)
        
        def waitElement(element, timeout):
            #log
            timeout_date = datetime.now() + timedelta(seconds=timeout)
            date = datetime.now()

            while timeout_date > date:
                try:
                    return getElement(element)
                except Exception as e:
                    exeption = e
                    date = datetime.now()
                    #log
            raise Exception("TIMEOUT - Element no reachable")
        
        def focus(element):
            #log
            web_element = getElement(element)
            location = web_element.location
            self.driver.execute_script("window.scrollTo(0, "+ str(location['y']) +")")

        def click(element):
            #log
            web_element = getElement(element)
            web_element.click()

        def tick(element, color):
            #log
            web_element = getElement(element)
            def apply_style(s):
                self.driver.execute_script("arguments[0].setAttribute('style', arguments[1]);",
                                    web_element, s)
            original_style = web_element.get_attribute('style')
            apply_style("border: 2px solid "+ color +";")
            time.sleep(.3)
            apply_style(original_style)

        def input_text(element, text):
            #log
            web_element = getElement(element)
            web_element.send_keys(text)

        def getText(element):
            #log
            web_element = getElement(element)
            return web_element.text
        
        def getAttribute(element, attribute):
            #log
            web_element = getElement(element)
            return web_element.get_attribute(attribute)
        
        def clear(element):
            #log
            web_element = getElement(element)
            web_element.clear()

        # ... Agrega aquí TODAS las demás funciones que tus scripts usan:
        # getText, getAttribute, waitElement, sleep, etc.
        
        return {
            "get": get,
            "click": click,
            "input": input_text, # Renombrada para evitar conflicto con la función built-in 'input'
            "assertion": assertion,
            "writeGlobalEvidence": writeGlobalEvidence,
            "writeCaseEvidence": writeCaseEvidence,
            "writeEvidence": writeEvidence,
            "sleep": sleep,
            "consumeService": consumeService,
            "executeQuery": executeQuery,
            "sendJmsQueue": sendJmsQueue,
            "sendMail": sendMail,
            "getGsheet": getGsheet,
            "getElement": getElement,
            "waitElement": waitElement,
            "focus": focus,
            "tick": tick,
            "getText": getText,
            "getAttribute": getAttribute,
            "clear": clear,
            # Asegúrate de pasar el resto de funciones necesarias
            "caseData": None, # Placeholder que se llenará por cada caso
            "__builtins__": __builtins__ # Permite usar funciones estándar de Python
        }

    def _execute_case(self, script, case_data_row, executor):
        """Ejecuta un único caso de prueba."""
        _, case_data = case_data_row
        logging.info(f"Ejecutando caso con datos: {case_data.to_dict()}")

        try:
            with self.engine.connect() as connection:
                query = "SELECT * FROM test_executor.stop_execution as e WHERE e.execution_id = '" + self.test_execution_data['test_execution_id'] + "'"
                result = connection.execute(text(query)).first()
                #print('-------------aqui---------' + str(result))
                if result:
                    self.test_execution_data['status'] = "stopped"
                    executor.shutdown(wait=False, cancel_futures=True)
            
            self.case_execution_data['case_execution_id'] = utils.generateRandomId("ce")
            self.case_execution_data['test_execution_id'] = self.test_execution_data['test_execution_id']

            script_globals = self._get_script_globals()
            script_globals['caseData'] = case_data # Inyecta los datos del caso actual

            os.mkdir(os.getenv('EVIDENCE_FILE_DIR')+ '/' + self.test_execution_data['test_execution_id'] +
                    '/' + self.case_execution_data['case_execution_id'] + '/')
            self.case_execution_data['case_results_dir'] = os.getenv('EVIDENCE_FILE_DIR')+ '/' + \
                self.test_execution_data['test_execution_id'] + '/' + \
                self.case_execution_data['case_execution_id'] + '/'
            
            self.case_execution_data['status'] = "Succes"
            
            # exec() ejecutará el script usando las funciones personalizadas que tienen acceso a 'self'
            exec(script, script_globals)
        except Exception as e:
            logging.error(f"Falló la ejecución del caso para {self.test_execution_id}: {e}", exc_info=True)
            self.test_execution_data['status'] = 'failed'
            # Aquí tu lógica para registrar el fallo del caso
        
        self.sendqueue("tasks.insert_case_execution", self.case_execution_data)
    
    def run(self):
        """
        El método principal que orquesta toda la ejecución de la prueba.
        Este es el 'target' para el hilo.
        """
        try:
            self._create_environment()

            script = self.config['script']
            test_cases_file_uri = os.getenv('TEST_CASES_DIR') + self.getCase(self.config['test_cases_file'])
            # Evaluar scripts
            data = pandas.read_csv(test_cases_file_uri)

            self.test_execution_data['test_execution_id'] = self.config['test_execution_id']
            self.test_execution_data['test_cases_size'] = len(data.index)
            self.test_execution_data['status'] = 'success'
            os.mkdir(os.getenv('EVIDENCE_FILE_DIR') + '/' +
                    self.test_execution_data['test_execution_id'] + '/')

            # Ejecutar 'before_script' si existe
            if self.config.get('before_script'):
                logging.info("Ejecutando before_script...")
                self.executeBeforeOrAfter(self.config['before_script'])

            # Usar ThreadPoolExecutor para ejecutar los casos en paralelo
            with ThreadPoolExecutor(max_workers=self.config.get('threads', 1)) as executor:
                futures = [executor.submit(self._execute_case, script, row, executor) for row in data.iterrows()]
                # Esperar a que todos los casos terminen
                for future in futures:
                    future.result() 

            self.generateFiles(1)

            # Ejecutar 'after_script' si existe
            if self.config.get('after_script'):
                logging.info("Ejecutando after_script...")
                self.executeBeforeOrAfter(self.config['after_script'])

        except Exception as e:
            logging.error(f"Error catastrófico en la ejecución {self.test_execution_id}: {e}", exc_info=True)
            self.test_execution_data['status'] = 'failed'
        finally:
            self._cleanup()
            self.sendqueue("tasks.update_test_execution", self.test_execution_data)
            logging.info(f"Ejecución {self.test_execution_id} finalizada con estado: {self.test_execution_data['status']}")

    def responseMapper(self, response, request):
        #print("response: " + str(response['status_code']))
        #print("response: " + str(response['headers']))
        if 'html' in response['headers']['Content-Type'] and request['service_type'] == 'SCRAPING':
            body = BeautifulSoup(response['body'], 'html.parser')
        elif 'xml' in response['headers']['Content-Type']:
            body = minidom.parseString(response['body'])
        else:
            body = response['body']
        #print('typo de body es: ' + str(type(body)))
        response['body'] = body
        return response

    def defaultResponseMapper(self, response, request):
        #print("response: " + str(response['status_code']))
        #print("response: " + str(response['headers']))
        #print("response: " + str(response))
        #body = response['body']
        #print('typo de body es: ' + str(type(body)))
        #response['body'] = body
        return response
    
    def sendqueue(self, queueName, message):
        params = pika.URLParameters(os.getenv('RABBIT_SERVER_URL'))
        params.socket_timeout = 5

        connection = pika.BlockingConnection(params)  # Connect to CloudAMQP
        channel = connection.channel()  # start a channel
        #channel.queue_declare(queue=queueName)  # Declare a queue
        # send a message

        channel.basic_publish(
            exchange='', routing_key=queueName, body=str(message))
        #print("[x] Message sent to consumer")
        connection.close()

    def generateFiles(self, fileType):
        logging.info('Generating evidence files for ' + str(fileType))
        with self.engine.connect() as connection:
            if fileType == 1:
                query = "SELECT * FROM test_executor.evidence_file as e WHERE e.test_execution_id = '" + \
                    self.test_execution_data['test_execution_id'] + \
                        "' AND e.type_id = " + str(fileType) + ";"
            else:
                query = "SELECT * FROM test_executor.evidence_file as e WHERE e.test_execution_id = '" + \
                    self.test_execution_data['test_execution_id'] + "' AND e.case_execution_id = '" + \
                        self.case_execution_data['case_execution_id'] + \
                    "' AND e.type_id = " + str(fileType) + ";"
            result = connection.execute(text(query))
            #print(type(result))
            for row in result:
                #print(type(row))
                query = "SELECT * FROM test_executor.case_evidence as e WHERE e.evidence_id = '" + \
                    row.evidence_id + "' ORDER BY creation_date ASC"
                rs = connection.execute(text(query))
                df = pandas.DataFrame(rs.fetchall())
                if not df.empty:
                    df.columns = rs.keys()
                    # mejorar
                    evidence_text = df.get(['evidence_text'])
                    file = open(row.evidence_uri, "w")
                    np.savetxt(file, evidence_text.values, fmt='%s')
                    file.close()
    
    def getCase(slef, dir: str):
        list_dir = dir.split('/')
        return list_dir[len(list_dir) - 1]

    def executeBeforeOrAfter(self, script: str):
        try:
            self.case_execution_data['case_execution_id'] = utils.generateRandomId("ce")
            self.case_execution_data['test_execution_id'] = self.test_execution_data['test_execution_id']

            os.mkdir(os.getenv('EVIDENCE_FILE_DIR')+ '/' + self.test_execution_data['test_execution_id'] +
                    '/' + self.case_execution_data['case_execution_id'] + '/')
            self.case_execution_data['case_results_dir'] = os.getenv('EVIDENCE_FILE_DIR')+ '/' + \
                self.test_execution_data['test_execution_id'] + '/' + \
                self.case_execution_data['case_execution_id'] + '/'

            self.case_execution_data['status'] = "Succes"

            exec(script, self._get_script_globals())
        except Exception as e:
            self.case_execution_data['status'] = "Failed"
            self.test_execution_data['status'] = "failed"
            self.writeGlobalEvidence(
                self.test_execution_data['test_execution_id'] + "_failed_cases",  str(e.with_traceback))
        # crear archivos de evidencias unitarios
        self.generateFiles(2)
        # enviar datos del caso de prueba
        self.sendqueue("tasks.insert_case_execution", self.case_execution_data)