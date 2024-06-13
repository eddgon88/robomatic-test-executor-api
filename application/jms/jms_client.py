from ..services.test_executor_service import TestExecutorService
import pika
from aio_pika import connect_robust
import ast
import os
from dotenv import load_dotenv

load_dotenv()

class PikaClient:

    def __init__(self, process_callable):
        params = pika.URLParameters(os.getenv('RABBIT_SERVER_URL'))
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel() # start a channel
        #self.channel.queue_declare(queue='tasks.execute_test') # Declare a queue
        self.response = None
        self.process_callable = process_callable
        print('Pika connection initialized')

    async def consume_execute_test(self, loop):
        connection = await connect_robust(host="localhost",
                                        port=5672,
                                        login="admin",
                                        password="admin",
                                        loop=loop)
        channel = await connection.channel()
        queue = await channel.declare_queue('tasks.execute_test')
        await queue.consume(self.execute_test, no_ack=True)
        print('Established pika async listener')
        return connection

    def execute_test(self, message):
        #message.ack()
        body = message.body
        print('Received message')
        print(body)
        if body:
            body_str = body.decode("UTF-8")
            content = ast.literal_eval(body_str)  
            TestExecutorService.executeTest(content)
    
    async def consume_stop_test_execution(self, loop):
        connection = await connect_robust(host="localhost",
                                        port=5672,
                                        login="admin",
                                        password="admin",
                                        loop=loop)
        channel = await connection.channel()
        queue = await channel.declare_queue('tasks.stop_test_execution')
        await queue.consume(self.stop_test_execution, no_ack=True)
        print('Established pika async listener')
        return connection

    def stop_test_execution(self, message):
        #message.ack()
        body = message.body
        print('Received message')
        print(body)
        if body:
            body_str = body.decode("UTF-8")
            content = ast.literal_eval(body_str)  
            TestExecutorService.stop_test(content)