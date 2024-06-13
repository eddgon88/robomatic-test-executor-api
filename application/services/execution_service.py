from sqlalchemy import text, create_engine
from ..models.models import ExecutionPorts
import os
from dotenv import load_dotenv

load_dotenv()

engine = create_engine(os.getenv('DB_SERVER_URL'))


class ExecutionService:
    @staticmethod
    def get_execution_vnc_port(execution_id: str):
        with engine.connect() as connection:
            query = "SELECT * FROM test_executor.test_port as e WHERE e.execution_id = '" + \
                execution_id + "'"
            result = connection.execute(text(query)).first()
            print('-------------aqui---------' + str(result))
            if result:
                return ExecutionPorts(id=result.id,
                                      execution_id=execution_id,
                                      selenium_port=result.selenium_port,
                                      vnc_port=result.vnc_port)
