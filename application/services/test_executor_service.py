import sys
import pandas
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from .. import utils
from sqlalchemy import text, create_engine
from datetime import datetime
import time
import os
from fastapi import Depends
import logging
import pika
import requests
import json
from bs4 import BeautifulSoup
from xml.dom import minidom
from pydantic import EmailStr
from threading import Event

logging.basicConfig(level=logging.INFO,
                    format='(%(threadName)-10s) %(message)s',)
test_execution_data = {}
case_execution_data = {}
# pasar por conf
engine = create_engine(
    'postgresql://robomatic:robomatic@localhost:5432/test_executor')
event = Event()


class TestExecutorService:
    @staticmethod
    def executeTest(excecuteObject):
        #current_app.logger.info(
        #    'Executing test ' + excecuteObject['name'])
        logging.info('Executing test ' + excecuteObject['name'])
        testCasesFileUri = excecuteObject['test_cases_file']
        script = excecuteObject['script']
        # Evaluar script
        data = pandas.read_csv(testCasesFileUri)
        test_execution_data['test_execution_id'] = excecuteObject['test_execution_id']
        test_execution_data['test_cases_size'] = len(data.index)
        test_execution_data['status'] = 'success'
        os.mkdir('/home/edgar/robomatic/github/evidence/' +
                 test_execution_data['test_execution_id'] + '/')
        with ThreadPoolExecutor(max_workers=excecuteObject['threads']) as executor:
            futures = {executor.submit(
                executeCase, script, row, executor): row for row in data.iterrows()}
            #for future in futures:
            #    if future.cancelled():
            #        continue
            #    with engine.connect() as connection:
            #        query = "SELECT * FROM test_executor.evidence_file as e WHERE e.file_name = '" + test_execution_data['test_execution_id'] + "'"
            #        result = connection.execute(text(query)).first()
            #        print(result)
            #        if result:
            #            executor.shutdown(wait=False, cancel_futures=True)
        executor.shutdown(wait=True)

        # crear los archivos de evidencias globales
        generateFiles(1)
        # enviar datos de la ejecución al core
        sendqueue("tasks.update_test_execution", test_execution_data)

    @staticmethod
    def stop_test(testExecution):
        print("stopping test")
        with engine.connect() as connection:
            query = "INSERT INTO test_executor.stop_execution (execution_id) VALUES('"+testExecution['test_execution_id']+"')"
            connection.execute(text(query))

def executeCase(script: str, data, executor):
    try:
        with engine.connect() as connection:
            query = "SELECT * FROM test_executor.stop_execution as e WHERE e.execution_id = '" + test_execution_data['test_execution_id'] + "'"
            result = connection.execute(text(query)).first()
            print('-------------aqui---------' + str(result))
            if result:
                test_execution_data['status'] = "stopped"
                executor.shutdown(wait=False, cancel_futures=True)
        print('execute case 1')
        print(data)
        (l, caseData) = data
        print('execute case 2')
        case_execution_data['case_execution_id'] = utils.generateRandomId("ce")
        case_execution_data['test_execution_id'] = test_execution_data['test_execution_id']
        print('execute case 3')

        logging.info('Executing Case')
        print('execute case 4')

        os.mkdir('/home/edgar/robomatic/github/evidence/' + test_execution_data['test_execution_id'] +
                 '/' + case_execution_data['case_execution_id'] + '/')
        case_execution_data['case_results_dir'] = '/home/edgar/robomatic/github/evidence/' + \
            test_execution_data['test_execution_id'] + '/' + \
            case_execution_data['case_execution_id'] + '/'
        print('execute case 5')

        case_execution_data['status'] = "Succes"
        print('execute case 6')

        exec(script)
    except Exception as e:
        print("Failed exec")
        print(e.with_traceback)
        print(format(e))
        #current_app.logger.error('Case execution failed: ' + e.with_traceback)
        case_execution_data['status'] = "Failed"
        test_execution_data['status'] = "failed"
        writeGlobalEvidence(
            test_execution_data['test_execution_id'] + "_failed_cases",  str(e.with_traceback))
    # crear archivos de evidencias unitarios
    generateFiles(2)
    # enviar datos del caso de prueba
    sendqueue("tasks.insert_case_execution", case_execution_data)
    return True


def sendqueue(queueName, message):
    params = pika.URLParameters('amqp://admin:admin@127.0.0.1:5672')
    params.socket_timeout = 5

    connection = pika.BlockingConnection(params)  # Connect to CloudAMQP
    channel = connection.channel()  # start a channel
    #channel.queue_declare(queue=queueName)  # Declare a queue
    # send a message

    channel.basic_publish(
        exchange='', routing_key=queueName, body=str(message))
    print("[x] Message sent to consumer")
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
            date = datetime.today()
            query = "INSERT INTO test_executor.case_evidence (evidence_id,evidence_text, creation_date) VALUES ('" + \
                evidence_file_id+"','"+content+"', '"+str(date)+"');"
            connection.execute(text(query))
    else:
        evidence_file_id = utils.generateRandomId("ef")
        file_name = fileName + '.txt'
        if fileType == 1:
            evidence_uri = '/home/edgar/robomatic/github/evidence/' + \
                test_execution_data['test_execution_id'] + \
                '/' + fileName + '.txt'
        else:
            evidence_uri = '/home/edgar/robomatic/github/evidence/' + test_execution_data['test_execution_id'] + \
                '/' + \
                case_execution_data['case_execution_id'] + \
                '/' + fileName + '.txt'
        test_execution_id = test_execution_data['test_execution_id']
        with engine.connect() as connection:
            query = "INSERT INTO test_executor.evidence_file (evidence_id,file_name,evidence_uri, type_id, test_execution_id, case_execution_id) VALUES ('" + \
                evidence_file_id+"','"+file_name+"','"+evidence_uri+"'," + \
                    str(fileType)+",'"+test_execution_id+"','" + \
                case_execution_data['case_execution_id']+"');"
            connection.execute(text(query))
            date = datetime.today()
            query = "INSERT INTO test_executor.case_evidence (evidence_id,evidence_text, creation_date) VALUES ('" + \
                evidence_file_id+"','"+content+"', '"+str(date)+"');"
            connection.execute(text(query))


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
        print(type(result))
        for row in result:
            print(type(row))
            query = "SELECT * FROM test_executor.case_evidence as e WHERE e.evidence_id = '" + \
                row.evidence_id + "'"
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
    print(type(request))
    logging.info('calling some service ' + request['url'])
    json_request = json.dumps(request)
    r = requests.post(
        'http://localhost:5002/rest-api/v1/consume', data=json_request)
    return responseMapper(r.json(), request)


def executeQuery(dbconfig):
    logging.info('executing some query ' + dbconfig['query'])
    json_request = json.dumps(dbconfig)
    r = requests.post(
        'http://localhost:5003/database-api/v1/execute', data=json_request)
    return r.json()


def sendJmsQueue(jmsconfig):
    logging.info('sending some queue to' + jmsconfig['engine'])
    json_request = json.dumps(jmsconfig)
    r = requests.post(
        'http://localhost:5004/jms-api/v1/sendqueue', data=json_request)
    return r.content


def responseMapper(response, request):
    print("response: " + str(response['status_code']))
    print("response: " + str(response['headers']))
    if 'html' in response['headers']['Content-Type'] and request['service_type'] == 'SCRAPING':
        body = BeautifulSoup(response['body'], 'html.parser')
    elif 'xml' in response['headers']['Content-Type']:
        body = minidom.parseString(response['body'])
    else:
        body = response['body']
    print('typo de body es: ' + str(type(body)))
    response['body'] = body
    return response

def defaultResponseMapper(response, request):
    #print("response: " + str(response['status_code']))
    #print("response: " + str(response['headers']))
    print("response: " + str(response))
    #body = response['body']
    #print('typo de body es: ' + str(type(body)))
    #response['body'] = body
    return response

def sendMail(mails, subject, body, files, template_id):
    mail_array = mails.split(',')
    print("------------------------------" + str(type(body)) + "-----------------------------")
    if str(type(body)) == "<class 'str'>":
        body_dict = None
        body_str = body
    else:
        body_dict = body
        body_str = ""
    file_array = files.split(',')
    message = {
        "email": mail_array,
        "subject": subject,
        "body": body_str,
        "body_dict": body_dict,
        "template_id": template_id,
        "files": file_array
    }
    sendqueue("tasks.send_mail", message)

def getGsheet(request):
    print(type(request))
    logging.info('calling some gsheet ' + request['file_id'])
    json_request = json.dumps(request)
    r = requests.post(
        'http://localhost:5008/gdrive-api/vi/consume', data=json_request)
    return defaultResponseMapper(r.json(), request)