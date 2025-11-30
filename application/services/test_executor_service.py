import pandas
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from .. import utils
from sqlalchemy import text, create_engine
from datetime import datetime
import time
import os
import logging
import pika
import requests
import json
from bs4 import BeautifulSoup
from xml.dom import minidom
from threading import Event
import threading
from selenium import webdriver
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from ..services.docker_service import DockerService
from dotenv import load_dotenv
from typing import List
from pydantic import EmailStr
import unicodedata
import re

logging.basicConfig(level=logging.INFO,
                    format='(%(threadName)-10s) %(message)s',)

local_storage = threading.local()
test_execution_data = {}
case_execution_data = {}
load_dotenv()
engine = create_engine(os.getenv('DB_SERVER_URL'))
event = Event()


class TestExecutorService:
    @staticmethod
    def executeTest(excecuteObject):
        dockerService = DockerService()
        #current_app.logger.info(
        #    'Executing test ' + excecuteObject['name'])
        logging.info('Executing test ' + excecuteObject['name'])
        testCasesFileUri = os.getenv('TEST_CASES_DIR') + getCase(excecuteObject['test_cases_file'])
        script = excecuteObject['script']
        before_script = excecuteObject['before_script']
        after_script = excecuteObject['after_script']
        # Evaluar scripts
        data = pandas.read_csv(testCasesFileUri)
        test_execution_data['test_execution_id'] = excecuteObject['test_execution_id']
        test_execution_data['test_cases_size'] = len(data.index)
        test_execution_data['status'] = 'success'
        os.mkdir(os.getenv('EVIDENCE_FILE_DIR') + '/' +
                 test_execution_data['test_execution_id'] + '/')
        
        if excecuteObject['web']:
            ports = dockerService.createDocker()
            logging.info('Selenium hub docker runnig -  ' + str(ports))
            options = webdriver.ChromeOptions()
            options.add_argument("--disable-notifications")
            options.add_experimental_option("prefs", {
                "profile.default_content_setting_values.notifications": 2  # 2 = bloquear
            })
            time.sleep(10)
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    local_storage.driver = webdriver.Remote(
                        command_executor='http://'+str(ports[1].name)+':'+str(ports[0][0]),
                        #command_executor='http://localhost:4444',
                        options=options
                    )
                    break
                except Exception as e:
                    logging.warning(f"Intento fallido: {str(e)}")
                    if attempt == max_attempts - 1:
                        dockerService.destroy_docker(str(ports[1].name))
                        raise Exception(f"No se pudo conectar a Selenium tras {max_attempts} intentos: {str(e)}")
                    time.sleep(5)
            
            with engine.connect() as connection:
                try:
                    trans = connection.begin()
                    webquery = text("""
                        INSERT INTO test_executor.test_port (execution_id, selenium_port, vnc_port) 
                        VALUES (:execution_id, :selenium_port, :vnc_port)
                    """)
                    
                    # Parameters to prevent SQL injection
                    params = {
                        'execution_id': test_execution_data['test_execution_id'],
                        'selenium_port': str(ports[0][0]),
                        'vnc_port': str(ports[0][1])
                    }
                    
                    result = connection.execute(webquery, params)
                    
                    # For INSERT operations, print the row count and primary key value (if any)
                    logging.info(f"Rows affected: {result.rowcount}")
                    logging.info(f"Last inserted ID: {result.lastrowid}")
                    trans.commit()  # Commit the transaction
                    
                except Exception as e:
                    logging.error(f"An error occurred: {e}")
                    trans.rollback() 
        
        executeBeforeOrAfter(before_script)

        with ThreadPoolExecutor(max_workers=excecuteObject['threads']) as executor:
            futures = {executor.submit(
                executeCase, script, row, executor, local_storage.driver): row for row in data.iterrows()}
        executor.shutdown(wait=True)

        generateFiles(1)

        executeBeforeOrAfter(after_script)

        if excecuteObject['web']:
            if getattr(local_storage, 'driver', None):
                try:
                    local_storage.driver.quit()
                    logging.info("Sesión de WebDriver cerrada.")
                except Exception as e:
                    logging.warning(f"Error al cerrar la sesión de WebDriver: {e}")
                local_storage.driver = None # Limpia la referencia

            dockerService.destroy_docker(str(ports[1].name))

        # crear los archivos de evidencias globales
        # enviar datos de la ejecución al core
        sendqueue("tasks.update_test_execution", test_execution_data)

    @staticmethod
    def stop_test(testExecution):
        print("stopping test")
        with engine.connect() as connection:
            try:
                trans = connection.begin()
                query = "INSERT INTO test_executor.stop_execution (execution_id) VALUES('"+testExecution['test_execution_id']+"')"
                connection.execute(text(query))
                trans.commit()  # Commit the transaction                 
            except Exception as e:
                logging.error(f"An error occurred: {e}")
                trans.rollback() 

def get_driver_from_thread():
    """Función auxiliar para obtener el driver del hilo actual de forma segura."""
    driver = getattr(local_storage, 'driver', None)
    if not driver:
        # Esto puede pasar si se llama una función web fuera de una ejecución de prueba con web=true
        raise RuntimeError("WebDriver no está inicializado en este contexto/hilo.")
    return driver

def getCase(dir: str):
    list_dir = dir.split('/')
    return list_dir[len(list_dir) - 1]

def executeBeforeOrAfter(script: str):
    try:
        case_execution_data['case_execution_id'] = utils.generateRandomId("ce")
        case_execution_data['test_execution_id'] = test_execution_data['test_execution_id']

        os.mkdir(os.getenv('EVIDENCE_FILE_DIR')+ '/' + test_execution_data['test_execution_id'] +
                 '/' + case_execution_data['case_execution_id'] + '/')
        case_execution_data['case_results_dir'] = os.getenv('EVIDENCE_FILE_DIR')+ '/' + \
            test_execution_data['test_execution_id'] + '/' + \
            case_execution_data['case_execution_id'] + '/'

        case_execution_data['status'] = "Succes"

        exec(script)
    except Exception as e:
        case_execution_data['status'] = "Failed"
        test_execution_data['status'] = "failed"
        writeGlobalEvidence(
            test_execution_data['test_execution_id'] + "_failed_cases",  str(e.with_traceback))
    # crear archivos de evidencias unitarios
    generateFiles(2)
    # enviar datos del caso de prueba
    sendqueue("tasks.insert_case_execution", case_execution_data)
    return True

def executeCase(script: str, data, executor, driver_instance):
    local_storage.driver = driver_instance
    try:
        with engine.connect() as connection:
            query = "SELECT * FROM test_executor.stop_execution as e WHERE e.execution_id = '" + test_execution_data['test_execution_id'] + "'"
            result = connection.execute(text(query)).first()
            #print('-------------aqui---------' + str(result))
            if result:
                test_execution_data['status'] = "stopped"
                executor.shutdown(wait=False, cancel_futures=True)
        #print('execute case 1')

        logging.info(data)
        (l, caseData) = data
        logging.info(caseData)
        #print('execute case 2')
        case_execution_data['case_execution_id'] = utils.generateRandomId("ce")
        case_execution_data['test_execution_id'] = test_execution_data['test_execution_id']
        #print('execute case 3')

        logging.info('Executing Case')
        #print('execute case 4')

        os.mkdir(os.getenv('EVIDENCE_FILE_DIR')+ '/' + test_execution_data['test_execution_id'] +
                 '/' + case_execution_data['case_execution_id'] + '/')
        case_execution_data['case_results_dir'] = os.getenv('EVIDENCE_FILE_DIR')+ '/' + \
            test_execution_data['test_execution_id'] + '/' + \
            case_execution_data['case_execution_id'] + '/'
        #print('execute case 5')

        case_execution_data['status'] = "Succes"
        #print('execute case 6')

        exec(script)
    except Exception as e:
        logging.error("Failed exec")
        #print(e.with_traceback)
        logging.error(format(e))
        #current_app.logger.error('Case execution failed: ' + e.with_traceback)
        case_execution_data['status'] = "Failed"
        test_execution_data['status'] = "failed"
        writeGlobalEvidence(
            test_execution_data['test_execution_id'] + "_failed_cases",  str(format(e)).replace('\'', ''))
    # crear archivos de evidencias unitarios
    generateFiles(2)
    # enviar datos del caso de prueba
    sendqueue("tasks.insert_case_execution", case_execution_data)
    return True
    
def sendqueue(queueName, message):
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


def printMethod(name: str, lastName: str):
    print("hola " + name + " " + lastName + ", desde el metodo printMethod()")


def writeGlobalEvidence(fileName, content):
    logging.info('writing global evidence: ' + fileName)
    writeEvidence(fileName, content, 1)


def writeCaseEvidence(fileName, content):
    logging.info('writing unitary evidence: ' + fileName)
    writeEvidence(fileName, content, 2)


def writeEvidence(fileName, content, fileType):
    query = "SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = '" + fileName + \
        ".txt' and e.test_execution_id = '" + \
            test_execution_data['test_execution_id'] + "'"
    if fileType == 1:
        query = "SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = '" + fileName + \
            ".txt' and e.test_execution_id = '" + \
                test_execution_data['test_execution_id'] + "'"
    else:
        query = "SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = '" + fileName + ".txt' and e.test_execution_id = '" + \
            test_execution_data['test_execution_id'] + "' AND e.case_execution_id = '" + \
                case_execution_data['case_execution_id'] + "'"
    with engine.connect() as connection:
        result = connection.execute(text(query)).first()
    if result:
        evidence_file_id = result.evidence_id
        with engine.connect() as connection:
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
                test_execution_data['test_execution_id'] + \
                '/' + fileName + '.txt'
        else:
            evidence_uri = os.getenv('EVIDENCE_FILE_DIR')+ '/' + test_execution_data['test_execution_id'] + \
                '/' + \
                case_execution_data['case_execution_id'] + \
                '/' + fileName + '.txt'
        test_execution_id = test_execution_data['test_execution_id']
        with engine.connect() as connection:
            try:
                trans = connection.begin()
                query = "INSERT INTO test_executor.evidence_file (evidence_id,file_name,evidence_uri, type_id, test_execution_id, case_execution_id) VALUES ('" + \
                    evidence_file_id+"','"+file_name+"','"+evidence_uri+"'," + \
                        str(fileType)+",'"+test_execution_id+"','" + \
                    case_execution_data['case_execution_id']+"');"
                connection.execute(text(query))
                date = datetime.today()
                query = "INSERT INTO test_executor.case_evidence (evidence_id,evidence_text, creation_date) VALUES ('" + \
                    evidence_file_id+"','"+content+"', '"+str(date)+"');"
                connection.execute(text(query))
                trans.commit()
            except Exception as e:
                    logging.error(f"An error occurred: {e}")
                    trans.rollback()    


def sleep(s):
    logging.info('sleeping for ' + str(s) + ' seconds')
    time.sleep(s)


def assertion(boul, message):
    if not boul:
        case_execution_data['status'] = "Failed"
        test_execution_data['status'] = "failed"
        logging.error(message)
        writeCaseEvidence(
            test_execution_data['test_execution_id'] + "_failed_assertions",  message)


def generateFiles(fileType):
    logging.info('Generating evidence files for ' + str(fileType))
    with engine.connect() as connection:
        if fileType == 1:
            query = "SELECT * FROM test_executor.evidence_file as e WHERE e.test_execution_id = '" + \
                test_execution_data['test_execution_id'] + \
                    "' AND e.type_id = " + str(fileType) + ";"
        else:
            query = "SELECT * FROM test_executor.evidence_file as e WHERE e.test_execution_id = '" + \
                test_execution_data['test_execution_id'] + "' AND e.case_execution_id = '" + \
                    case_execution_data['case_execution_id'] + \
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


def consumeService(request):
    #print(type(request))
    logging.info('calling some service ' + request['url'])
    json_request = json.dumps(request)
    r = requests.post(
        os.getenv('REST_API_URL'), data=json_request)
    return responseMapper(r.json(), request)


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


def responseMapper(response, request):
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

def defaultResponseMapper(response, request):
    #print("response: " + str(response['status_code']))
    #print("response: " + str(response['headers']))
    #print("response: " + str(response))
    #body = response['body']
    #print('typo de body es: ' + str(type(body)))
    #response['body'] = body
    return response

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
        "execution_id": test_execution_data['test_execution_id'],
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
    return defaultResponseMapper(r.json(), request)

def get(url):
    driver = get_driver_from_thread()
    driver.get(url)
    #driver.fullscreen_window()

def getElement(element):
    driver = get_driver_from_thread()
    by_array = [By.XPATH, By.ID]
    for by in by_array:
        try:
            return driver.find_element(by, element)
        except Exception as e:
            exeption = e
            #log
    raise Exception("Element no reachable")

def waitElement(element, timeout):
    #log
    driver = get_driver_from_thread()
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
    driver = get_driver_from_thread()
    web_element = getElement(element)
    location = web_element.location
    window_position = driver.get_window_position()
    driver.execute_script("window.scrollTo(0, "+ str(location['y']) +")") 

def click(element):
    #log
    driver = get_driver_from_thread()
    web_element = getElement(element)
    web_element.click()

def tick(element, color):
    #log
    driver = get_driver_from_thread()
    web_element = getElement(element)
    def apply_style(s):
        driver.execute_script("arguments[0].setAttribute('style', arguments[1]);",
                              web_element, s)
    original_style = web_element.get_attribute('style')
    apply_style("border: 2px solid "+ color +";")
    time.sleep(.3)
    apply_style(original_style)

def input(element, text):
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
