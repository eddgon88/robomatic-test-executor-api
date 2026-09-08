import pandas
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from .. import utils
from sqlalchemy import text, create_engine
from datetime import datetime, timedelta
import time
import os
import logging
import traceback
import pika

import requests
import json
from bs4 import BeautifulSoup
from xml.dom import minidom
from selenium import webdriver
from selenium.webdriver.common.by import By
from ..services.docker_service_v2 import DockerService # Asumido
from ..services.credential_service import CredentialService
from ..services.r2_storage_service import R2StorageService

from dotenv import load_dotenv
from lxml import etree

class StopExecutionException(Exception):
    """Excepción para detener la ejecución inmediatamente."""
    pass

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
        self.test_id = self.config.get('test_id')
        self.max_executions = self.config.get('max_executions', 0)
        self.current_executions = self.config.get('current_executions', 0)
        self.local_increments = 0
        
        # Atributos de estado específicos de esta instancia
        self.driver = None
        self.container = None
        self.docker_service = DockerService()
        self.engine = create_engine(os.getenv('DB_SERVER_URL'))
        self.r2_storage = R2StorageService()
 
        # Inicializar servicio de credenciales
        credentials = self.config.get('credentials', [])

        logging.info(f"Credentials received from core: {credentials}")
        logging.info(f"Number of credentials: {len(credentials) if credentials else 0}")
        self.credential_service = CredentialService(credentials)

        # Inicializar agentes de IA
        self.agents = self.config.get('agents', [])

        logging.info(f"AI Agents received from core: {len(self.agents)}")

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
        self.last_check_time = 0

    def _check_stop_signal(self):
        """Consulta periódicamente a la base de datos para ver si se solicitó detener la prueba."""
        current_time = time.time()
        # Solo verificar cada 2 segundos para no saturar la base de datos
        if current_time - self.last_check_time < 2:
            return

        self.last_check_time = current_time
        
        with self.engine.connect() as connection:
            query = "SELECT * FROM test_executor.stop_execution as e WHERE e.execution_id = '" + self.test_execution_data['test_execution_id'] + "'"
            result = connection.execute(text(query)).first()
            if result:
                 logging.info("Señal de stop detectada en base de datos.")
                 raise StopExecutionException("La ejecución fue detenida por el usuario.")

    def _create_environment(self):
        """Crea el contenedor de Docker o conecta con Browserless en Cloud Run y la instancia de WebDriver."""
        if not self.config.get('web'):
            return

        logging.info("Creando entorno web...")
        
        browserless_host = os.getenv("BROWSERLESS_HOST")
        browserless_token = os.getenv("BROWSERLESS_TOKEN")

        # =========================================================================
        # NUEVA IMPLEMENTACION: BROWSERLESS / SELENIUM STANDALONE EN GCP CLOUD RUN
        # =========================================================================
        if browserless_host:
            logging.info(f"Conectando a Selenium Standalone en Cloud Run ({browserless_host})...")
            options = webdriver.ChromeOptions()
            options.add_argument("--disable-notifications")
            options.add_argument("--start-maximized")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_experimental_option("prefs", {
                "profile.default_content_setting_values.notifications": 2
            })
            if browserless_token:
                options.set_capability("browserless:token", browserless_token)
                options.set_capability("browserless:stealth", True)
            if self.test_execution_id:
                options.set_capability("browserless:trackingId", str(self.test_execution_id))
            options.set_capability("se:vncEnabled", True)

            if browserless_host.startswith("http://") or browserless_host.startswith("https://"):
                base_url = browserless_host.rstrip('/')
            else:
                base_url = f"https://{browserless_host}"

            command_executor_url = base_url
            logging.info(f"Connecting WebDriver to Selenium Grid endpoint: {command_executor_url}...")

            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    self.driver = webdriver.Remote(
                        command_executor=command_executor_url,
                        options=options
                    )

                    logging.info(f"WebDriver conectado exitosamente a Selenium Grid para la ejecución {self.test_execution_id} con session_id: {getattr(self.driver, 'session_id', None)}")
                    break
                except Exception as e:
                    logging.warning(f"Intento de conexión a Selenium Grid fallido ({attempt + 1}/{max_attempts}): {str(e)}")
                    if attempt == max_attempts - 1:
                        raise Exception(f"No se pudo conectar a Selenium Grid tras {max_attempts} intentos: {str(e)}")
                    time.sleep(5)
            
            # Registrar sesión en base de datos si aplica
            with self.engine.connect() as connection:
                try:
                    trans = connection.begin()
                    webquery = text("""
                        INSERT INTO test_executor.test_port (execution_id, selenium_port, vnc_port, session_id) 
                        VALUES (:execution_id, :selenium_port, :vnc_port, :session_id)
                    """)
                    params = {
                        'execution_id': self.config['test_execution_id'],
                        'selenium_port': '443',
                        'vnc_port': '443',
                        'session_id': str(self.driver.session_id) if hasattr(self, 'driver') and self.driver and self.driver.session_id else None
                    }
                    result = connection.execute(webquery, params)
                    trans.commit()
                    logging.info(f"Puertos y session_id registrados para Browserless: {result.rowcount} filas (session_id={params['session_id']})")
                except Exception as e:
                    logging.error(f"Error al registrar puertos en test_port: {e}")
                    trans.rollback()
            return

        # =========================================================================
        # --- CODIGO ORIGINAL EC2 / DOCKER LOCAL (Preservado para compatibilidad) ---
        # =========================================================================
        # Recomiendo usar la versión mejorada de DockerService que espera a que el hub esté listo
        ports, self.container = self.docker_service.create_selenium_container()
        selenium_port, vnc_port = ports # Estos son los puertos en localhost
        logging.info(f"Contenedor creado: {self.container.name} con puertos {ports}")
        
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-notifications")
        options.add_argument("--start-maximized")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_experimental_option("prefs", {
                "profile.default_content_setting_values.notifications": 2  # 2 = bloquear
            })
        # options.add_argument("--headless") # Considerar para ejecuciones en servidor

        command_executor_url = f'http://{self.container.name}:4444'
        logging.info(f"Connecting WebDriver to {command_executor_url}...")


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
                        INSERT INTO test_executor.test_port (execution_id, selenium_port, vnc_port, session_id) 
                        VALUES (:execution_id, :selenium_port, :vnc_port, :session_id)
                    """)
                    
                    # Parameters to prevent SQL injection
                    params = {
                        'execution_id': self.config['test_execution_id'],
                        'selenium_port': str(selenium_port),
                        'vnc_port': str(vnc_port),
                        'session_id': str(self.driver.session_id) if hasattr(self, 'driver') and self.driver and self.driver.session_id else None
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
        """Limpia los recursos: cierra el driver y destruye el contenedor si fue local."""
        logging.info(f"Iniciando limpieza para {self.test_execution_id}")
        if self.driver:
            try:
                self.driver.quit()
                logging.info("Sesión de WebDriver cerrada.")
            except Exception as e:
                logging.warning(f"Error al cerrar WebDriver: {e}")
        
        # --- CODIGO ORIGINAL EC2 / DOCKER LOCAL (Solo si se creó contenedor) ---
        if self.container:
            self.docker_service.destroy_container(self.container.name)

    def _get_script_globals(self) -> dict:
        """
        Crea un diccionario de todas las funciones que el script de prueba puede llamar.
        Cada función "recuerda" el 'self' de esta instancia, dándole acceso a self.driver.
        ¡Esta es la clave para que los scripts no necesiten cambios!
        """
        def get(url):
            self._check_stop_signal()
            self.driver.get(url)

        def getElement(element):
            self._check_stop_signal()
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
            if fileType == 1:
                query = text("SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = :file_name and e.test_execution_id = :test_execution_id")
                params = {'file_name': fileName + ".txt", 'test_execution_id': self.test_execution_data['test_execution_id']}
            else:
                query = text("SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = :file_name and e.test_execution_id = :test_execution_id AND e.case_execution_id = :case_execution_id")
                params = {'file_name': fileName + ".txt", 'test_execution_id': self.test_execution_data['test_execution_id'], 'case_execution_id': self.case_execution_data['case_execution_id']}
            
            with self.engine.connect() as connection:
                result = connection.execute(query, params).first()
            if result:
                evidence_file_id = result.evidence_id
                with self.engine.connect() as connection:
                    try:
                        trans = connection.begin()
                        date = datetime.today()
                        ins_ev_query = text("INSERT INTO test_executor.case_evidence (evidence_id, evidence_text, creation_date) VALUES (:evidence_id, :evidence_text, :creation_date)")
                        connection.execute(ins_ev_query, {'evidence_id': evidence_file_id, 'evidence_text': str(content), 'creation_date': str(date)})
                        trans.commit() 
                    except Exception as e:
                        logging.error(f"An error occurred writing case evidence: {e}")
                        trans.rollback()      
            else:
                evidence_file_id = utils.generateRandomId("ef")
                file_name = fileName + '.txt'
                if fileType == 1:
                    evidence_uri = os.getenv('EVIDENCE_FILE_DIR', '/home/evidence') + '/' + \
                        self.test_execution_data['test_execution_id'] + \
                        '/' + fileName + '.txt'
                    case_exec_id = None
                else:
                    evidence_uri = os.getenv('EVIDENCE_FILE_DIR', '/home/evidence') + '/' + self.test_execution_data['test_execution_id'] + \
                        '/' + \
                        self.case_execution_data['case_execution_id'] + \
                        '/' + fileName + '.txt'
                    case_exec_id = self.case_execution_data['case_execution_id']
                
                test_execution_id = self.test_execution_data['test_execution_id']
                with self.engine.connect() as connection:
                    try:
                        trans = connection.begin()
                        ins_file_query = text("INSERT INTO test_executor.evidence_file (evidence_id, file_name, evidence_uri, type_id, test_execution_id, case_execution_id) VALUES (:evidence_id, :file_name, :evidence_uri, :type_id, :test_execution_id, :case_execution_id)")
                        connection.execute(ins_file_query, {
                            'evidence_id': evidence_file_id,
                            'file_name': file_name,
                            'evidence_uri': evidence_uri,
                            'type_id': fileType,
                            'test_execution_id': test_execution_id,
                            'case_execution_id': case_exec_id
                        })
                        date = datetime.today()
                        ins_ev_query = text("INSERT INTO test_executor.case_evidence (evidence_id, evidence_text, creation_date) VALUES (:evidence_id, :evidence_text, :creation_date)")
                        connection.execute(ins_ev_query, {
                            'evidence_id': evidence_file_id,
                            'evidence_text': str(content),
                            'creation_date': str(date)
                        })
                        trans.commit()
                    except Exception as e:
                        logging.error(f"An error occurred inserting evidence file/content: {e}")
                        trans.rollback()

        def writeGlobalEvidence(fileName, content):
            logging.info('writing global evidence: ' + fileName)
            writeEvidence(fileName, content, 1)

        def writeCaseEvidence(fileName, content):
            logging.info('writing unitary evidence: ' + fileName)
            writeEvidence(fileName, content, 2)

        def sleep(s):
            logging.info('sleeping for ' + str(s) + ' seconds')
            end_time = time.time() + s
            while time.time() < end_time:
                self._check_stop_signal()
                remaining = end_time - time.time()
                time.sleep(min(remaining, 0.5))
        
        def consumeService(request):
            self._check_stop_signal()
            #print(type(request))
            logging.info('calling some service ' + request['url'])
            json_request = json.dumps(request)
            r = requests.post(
                os.getenv('REST_API_URL'), data=json_request)
            return self.responseMapper(r.json(), request)
        
        def executeQuery(dbconfig):
            self._check_stop_signal()
            logging.info('executing some query ' + dbconfig['query'])
            json_request = json.dumps(dbconfig)
            r = requests.post(
                os.getenv('DATABASE_API_URL'), data=json_request)
            return r.json()
        
        def sendJmsQueue(jmsconfig):
            self._check_stop_signal()
            logging.info('sending some queue to: ' + jmsconfig['engine'])
            json_request = json.dumps(jmsconfig)
            r = requests.post(
                os.getenv('JMS_API_URL'), data=json_request)
            logging.info('sended queue: ' + str(r))
            return r.content
        
        def sendMail(mails, subject, body, files, template_id, md_file=None):
            self._check_stop_signal()
            logging.info('sending mail')
            mail_array = mails.split(',')
            
            markdown_body = None
            if md_file:
                try:
                    evidence_dir = os.getenv('EVIDENCE_FILE_DIR')
                    execution_id = self.test_execution_data['test_execution_id']
                    logging.info(f'Attempting to load markdown report. md_file: {md_file}, execution_id: {execution_id}, evidence_dir: {evidence_dir}')
                    
                    # El archivo podría ser una ruta completa o solo el nombre
                    if os.path.isabs(md_file) and os.path.exists(md_file):
                        md_path = md_file
                    else:
                        # Primero buscamos en la raíz de la ejecución
                        md_path = os.path.join(evidence_dir, execution_id, md_file)
                        if not os.path.exists(md_path):
                            # Si no está, lo buscamos en la carpeta del caso actual si existe
                            if 'case_execution_id' in self.case_execution_data:
                                md_path = os.path.join(evidence_dir, execution_id, self.case_execution_data['case_execution_id'], md_file)
                    
                    logging.info(f'Final path to search: {md_path}')
                    
                    if os.path.exists(md_path):
                        with open(md_path, 'r', encoding='utf-8') as f:
                            markdown_body = f.read()
                        logging.info(f'Markdown content loaded successfully (Length: {len(markdown_body)})')
                        if not template_id:
                            template_id = 'mail-report.html'
                    else:
                        logging.warning(f'Markdown file NOT FOUND at: {md_path}')
                        # Intento desesperado: buscar en toda la carpeta de evidencias de la ejecución
                        execution_folder = os.path.join(evidence_dir, execution_id)
                        if os.path.exists(execution_folder):
                            for root, dirs, files in os.walk(execution_folder):
                                if md_file in files:
                                    md_path = os.path.join(root, md_file)
                                    logging.info(f'Found markdown file in subfolder: {md_path}')
                                    with open(md_path, 'r', encoding='utf-8') as f:
                                        markdown_body = f.read()
                                    if not template_id:
                                        template_id = 'mail-report.html'
                                    break
                except Exception as e:
                    logging.error(f'Error reading markdown file: {e}')

            if str(type(body)) == "<class 'str'>":
                body_dict = None
                # No sobreescribir template_id si ya lo asignamos para markdown
                if not markdown_body:
                    template_id = None
                body_str = body
            else:
                body_dict = body
                body_str = ""
            
            file_array = files.split(',') if files else []
            message = {
                "email": mail_array,
                "subject": subject,
                "execution_id": self.test_execution_data['test_execution_id'],
                "body": body_str,
                "body_dict": body_dict,
                "template_id": template_id,
                "markdown_body": markdown_body,
                "files": file_array
            }
            r = requests.post(
                os.getenv('MAIL_API_URL'), json=message)
            logging.info('Mail sended')

        def getGsheet(request):
            self._check_stop_signal()
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
                self._check_stop_signal()
                try:
                    return getElement(element)
                except Exception as e:
                    exeption = e
                    date = datetime.now()
                    #log
            raise Exception("TIMEOUT - Element no reachable")
        
        def focus(element):
            #log
            self._check_stop_signal()
            web_element = getElement(element)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest', behavior: 'smooth'});", web_element)

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
            #apply_style(original_style)

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

        def getCredential(name):
            """
            Obtiene el valor de una credencial por su nombre.
            Para passwords: retorna el valor desencriptado
            Para certificados: retorna la ruta del archivo
            
            Uso:
                password = getCredential("db_password")
                cert_path = getCredential("ssl_certificate")
            """
            self._check_stop_signal()
            logging.info(f'Getting credential: {name}')
            return self.credential_service.get_credential(name)
        
        def incrementExecutionCount():
            self._check_stop_signal()
            logging.info(f"Incrementing execution count for test {self.test_id}")
            self.local_increments += 1
            now = datetime.now()
            message = {
                "test_id": self.test_id,
                "year": now.year,
                "month": now.month
            }
            self.sendqueue(os.getenv('INCREMENT_COUNT_QUEUE', 'tasks.increment_execution_count'), message)

        def hasAvailableExecutions():
            self._check_stop_signal()
            if self.max_executions == 0:
                return True
            available = (self.current_executions + self.local_increments) < self.max_executions
            logging.info(f"Checking available executions: {available} (Max: {self.max_executions}, Current/Local: {self.current_executions}/{self.local_increments})")
            return available

        def _log_ai_interaction(agent_name, prompt, response=None, status="SUCCESS", error_message=None):
            try:
                log_data = {
                    "testExecutionId": self.test_execution_id,
                    "agentName": agent_name,
                    "prompt": prompt,
                    "response": response,
                    "status": status,
                    "errorMessage": error_message
                }
                # Intentar derivar la URL del Core desde DATABASE_API_URL
                base_url = os.getenv('DATABASE_API_URL', '').split('/v1/')[0]
                if not base_url:
                    base_url = os.getenv('REST_API_URL', '').split('/v1/')[0]
                
                if base_url:
                    target_url = f"{base_url}/v1/ai-interactions/log"
                    requests.post(target_url, json=log_data, timeout=5)
            except Exception as e:
                logging.error(f"Failed to log AI interaction: {e}")

        def askAI(agentName: str, prompt: str, sessionId: str = None):
            """
            Llama al microservicio de IA para ejecutar un agente por su nombre.
            Incluye lógica de reintentos y logueo de interacciones.
            """
            self._check_stop_signal()
            
            # Buscar la configuración del agente por nombre
            agentConfig = next((a for a in self.agents if a.get('name') == agentName), None)
            if not agentConfig:
                msg = f"AI Agent '{agentName}' not found in assigned agents."
                logging.error(msg)
                raise Exception(msg)

            logging.info(f'Calling AI Agent: {agentName}')
            
            # Recolectar credenciales encriptadas
            credentials_data = {}
            for cred in self.config.get('credentials', []):
                name = cred.get('name')
                encrypted_value = cred.get('encrypted_value') or cred.get('encryptedValue')
                if name and encrypted_value:
                    credentials_data[name] = encrypted_value

            request_data = {
                "agent_config": agentConfig,
                "prompt": prompt,
                "session_id": sessionId,
                "credentials": credentials_data
            }

            max_retries = 3
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    r = requests.post(os.getenv("AI_API_URL"), data=json.dumps(request_data), timeout=90)
                    r.raise_for_status()
                    response_json = r.json()
                    
                    output = response_json.get("output")
                    new_session_id = response_json.get("session_id")
                    
                    # Log success
                    _log_ai_interaction(agentName, prompt, response=output)
                    return output, new_session_id
                    
                except Exception as e:
                    last_error = str(e)
                    logging.warning(f"AI interaction attempt {attempt + 1} failed for agent '{agentName}': {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2 * (attempt + 1)) # Simple backoff: 2s, 4s

            # If we reach here, all retries failed
            _log_ai_interaction(agentName, prompt, status="ERROR", error_message=last_error)
            raise Exception(f"AI Service Error after {max_retries} attempts: {last_error}")


        def convertFile(fileName, fileExtension):
            self._check_stop_signal()
            logging.info(f"Converting file {fileName} to {fileExtension}")
            payload = {
                "file_name": fileName,
                "file_extention": fileExtension,
                "execution_id": self.test_execution_id
            }
            url = f"{os.getenv('FILE_MANAGER_API_URL')}/file-manager-api/vi/convert"
            
            r = requests.post(url, json=payload)
            return r.json()

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
            "getCredential": getCredential,
            "incrementExecutionCount": incrementExecutionCount,
            "hasAvailableExecutions": hasAvailableExecutions,
            "askAI": askAI,
            "convertFile": convertFile,

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
                    executor.shutdown(wait=False)
            
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
        except StopExecutionException as e:
            logging.warning(f"Ejecución detenida: {e}")
            self.test_execution_data['status'] = 'stopped'
            executor.shutdown(wait=False)
        except Exception as e:
            logging.error(f"Falló la ejecución del caso para {self.test_execution_id}: {e}", exc_info=True)
            self.test_execution_data['status'] = 'failed'
            # Aquí tu lógica para registrar el fallo del caso
        
        self.sendqueue("tasks.insert_case_execution", self.case_execution_data)
    
    def write_global_evidence(self, file_name: str, content: str):
        """Escribe una evidencia global (tipo 1) en base de datos de forma parametrizada."""
        logging.info(f"Writing global evidence: {file_name}")
        query = text("SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = :file_name and e.test_execution_id = :test_execution_id")
        params = {'file_name': f"{file_name}.txt", 'test_execution_id': self.test_execution_id}
        
        with self.engine.connect() as connection:
            result = connection.execute(query, params).first()
        if result:
            evidence_file_id = result.evidence_id
            with self.engine.connect() as connection:
                try:
                    trans = connection.begin()
                    date = datetime.today()
                    ins_ev_query = text("INSERT INTO test_executor.case_evidence (evidence_id, evidence_text, creation_date) VALUES (:evidence_id, :evidence_text, :creation_date)")
                    connection.execute(ins_ev_query, {'evidence_id': evidence_file_id, 'evidence_text': str(content), 'creation_date': str(date)})
                    trans.commit()
                except Exception as e:
                    logging.error(f"An error occurred writing case evidence: {e}")
                    trans.rollback()
        else:
            evidence_file_id = utils.generateRandomId("ef")
            full_file_name = f"{file_name}.txt"
            evidence_dir = os.getenv('EVIDENCE_FILE_DIR', '/home/evidence')
            evidence_uri = f"{evidence_dir}/{self.test_execution_id}/{full_file_name}"
            with self.engine.connect() as connection:
                try:
                    trans = connection.begin()
                    ins_file_query = text("INSERT INTO test_executor.evidence_file (evidence_id, file_name, evidence_uri, type_id, test_execution_id) VALUES (:evidence_id, :file_name, :evidence_uri, 1, :test_execution_id)")
                    connection.execute(ins_file_query, {
                        'evidence_id': evidence_file_id,
                        'file_name': full_file_name,
                        'evidence_uri': evidence_uri,
                        'test_execution_id': self.test_execution_id
                    })
                    date = datetime.today()
                    ins_ev_query = text("INSERT INTO test_executor.case_evidence (evidence_id, evidence_text, creation_date) VALUES (:evidence_id, :evidence_text, :creation_date)")
                    connection.execute(ins_ev_query, {
                        'evidence_id': evidence_file_id,
                        'evidence_text': str(content),
                        'creation_date': str(date)
                    })
                    trans.commit()
                except Exception as e:
                    logging.error(f"An error occurred inserting evidence file/content: {e}")
                    trans.rollback()

    def run(self):
        """
        El método principal que orquesta toda la ejecución de la prueba.
        Este es el 'target' para el hilo.
        """
        evidence_base_dir = os.getenv('EVIDENCE_FILE_DIR', '/home/evidence')
        execution_dir = os.path.join(evidence_base_dir, self.config['test_execution_id'])
        os.makedirs(execution_dir, exist_ok=True)
        self.test_execution_data['test_execution_id'] = self.config['test_execution_id']

        try:
            self._create_environment()

            script = self.config['script']
            case_file_name = self.getCase(self.config['test_cases_file'])
            test_cases_dir = os.getenv('TEST_CASES_DIR', '/home/cases/')
            test_cases_file_uri = os.path.join(test_cases_dir, case_file_name)

            # Leer SIEMPRE directamente desde Cloudflare R2 como fuente principal
            case_bytes = None
            if self.r2_storage.is_enabled:
                for r2_case_key in [f"cases/{case_file_name}", case_file_name]:
                    case_bytes = self.r2_storage.get_file_bytes(r2_case_key)
                    if case_bytes:
                        logging.info(f"Casos de prueba obtenidos directamente desde Cloudflare R2: {r2_case_key}")
                        break

            if case_bytes:
                import io
                data = pandas.read_csv(io.BytesIO(case_bytes))
            elif os.path.exists(test_cases_file_uri):
                logging.info(f"Casos de prueba obtenidos desde fallback local: {test_cases_file_uri}")
                data = pandas.read_csv(test_cases_file_uri)
            else:
                raise FileNotFoundError(f"No se encontró el archivo de casos de prueba '{case_file_name}' en Cloudflare R2 ni en disco local.")



            self.test_execution_data['test_cases_size'] = len(data.index)
            self.test_execution_data['status'] = 'success'

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

        except StopExecutionException as e:
            logging.warning(f"Ejecución detenida en run loop: {e}")
            self.test_execution_data['status'] = 'stopped'
        except Exception as e:
            error_details = f"Error catastrófico en la ejecución {self.test_execution_id}: {str(e)}\n\nDetalles del Traceback:\n{traceback.format_exc()}"
            logging.error(error_details)
            self.test_execution_data['status'] = 'failed'
            try:
                self.write_global_evidence(f"{self.test_execution_id}_error", error_details)
                self.generateFiles(1)
            except Exception as ev_err:
                logging.error(f"Error generando evidencias de fallo: {ev_err}")
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
            exchange='', routing_key=queueName, body=json.dumps(message))
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
                    # mejorado con utf-8
                    evidence_text = df.get(['evidence_text'])
                    with open(row.evidence_uri, "w", encoding='utf-8') as file:
                        np.savetxt(file, evidence_text.values, fmt='%s', encoding='utf-8')

                    # --- SUBIDA AUTOMATICA A CLOUDFLARE R2 SI ESTA ACTIVO ---
                    if self.r2_storage.is_enabled:
                        try:
                            # Subir bajo prefijo 'evidence/{test_execution_id}/{file_name}'
                            r2_key = f"evidence/{self.test_execution_id}/{row.file_name}"
                            self.r2_storage.upload_file(row.evidence_uri, r2_key)
                            # También subir con clave simple '{test_execution_id}/{file_name}' para compatibilidad
                            self.r2_storage.upload_file(row.evidence_uri, f"{self.test_execution_id}/{row.file_name}")
                        except Exception as e:
                            logging.warning(f"Error al sincronizar evidencia {row.file_name} con R2: {e}")

    
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
        except StopExecutionException as e:
            raise e
        except Exception as e:
            self.case_execution_data['status'] = "Failed"
            self.test_execution_data['status'] = "failed"
            self.writeGlobalEvidence(
                self.test_execution_data['test_execution_id'] + "_failed_cases",  str(e.with_traceback))
        # crear archivos de evidencias unitarios
        self.generateFiles(2)
        # enviar datos del caso de prueba
        self.sendqueue("tasks.insert_case_execution", self.case_execution_data)