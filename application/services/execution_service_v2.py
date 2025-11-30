import os
import logging
from typing import Optional
from sqlalchemy import text, create_engine
from sqlalchemy.engine import Engine
from dotenv import load_dotenv
from ..models.models import ExecutionPorts # Asegúrate de que este import sea correcto

# Cargar variables de entorno una sola vez
load_dotenv()

# El logging se debería configurar en el punto de entrada de la aplicación
# logging.basicConfig(level=logging.INFO, format='(%(threadName)-10s) [%(levelname)s] %(message)s')

class ExecutionService:
    """
    Gestiona las interacciones con la base de datos relacionadas con las ejecuciones de pruebas.
    Cada instancia tiene su propio motor de base de datos para un aislamiento claro.
    """
    def __init__(self):
        """
        Inicializa el servicio y crea el motor de la base de datos.
        """
        db_url = os.getenv('DB_SERVER_URL')
        if not db_url:
            raise ValueError("La variable de entorno DB_SERVER_URL no está definida.")
            
        try:
            self.engine: Engine = create_engine(db_url)
            logging.info("ExecutionService instance created and database engine initialized.")
        except Exception as e:
            logging.error(f"Failed to create database engine: {e}")
            raise

    def get_execution_vnc_port(self, execution_id: str) -> Optional[ExecutionPorts]:
        """
        Obtiene los puertos de Selenium y VNC para una ejecución específica de forma segura.

        Args:
            execution_id: El ID de la ejecución a buscar.

        Returns:
            Un objeto ExecutionPorts si se encuentra, de lo contrario None.
        """
        # CORRECCIÓN DE SEGURIDAD: Se utiliza una consulta parametrizada para prevenir inyección de SQL.
        # El valor de 'execution_id' se inserta de forma segura donde está ':exec_id'.
        query = text("""
            SELECT id, execution_id, selenium_port, vnc_port
            FROM test_executor.test_port
            WHERE execution_id = :exec_id
        """)
        
        try:
            with self.engine.connect() as connection:
                # El diccionario de parámetros se pasa de forma segura al método execute.
                result = connection.execute(query, {"exec_id": execution_id}).first()
            
            if result:
                logging.info(f"Puertos encontrados para la ejecución {execution_id}: {result}")
                # Mapea la fila del resultado a tu modelo Pydantic/SQLAlchemy
                return ExecutionPorts(
                    id=result.id,
                    execution_id=result.execution_id,
                    selenium_port=result.selenium_port,
                    vnc_port=result.vnc_port
                )
            else:
                logging.warning(f"No se encontraron puertos para la ejecución con ID: {execution_id}")
                return None
        except Exception as e:
            logging.error(f"Error al obtener los puertos para la ejecución {execution_id}: {e}", exc_info=True)
            # Propagar el error o devolver None dependiendo de la política de manejo de errores.
            raise

    def stop_test(self, execution_id: str) -> bool:
        """
        Registra una solicitud para detener una ejecución de prueba de forma segura.

        Args:
            execution_id: El ID de la ejecución que se debe detener.
        
        Returns:
            True si la solicitud se registró correctamente, False en caso de error.
        """
        logging.info(f"Intentando registrar la detención para la ejecución: {execution_id}")
        
        # CORRECCIÓN DE SEGURIDAD: Consulta parametrizada.
        query = text("""
            INSERT INTO test_executor.stop_execution (execution_id) 
            VALUES (:exec_id)
        """)
        
        try:
            with self.engine.connect() as connection:
                with connection.begin() as transaction: # Inicia una transacción
                    connection.execute(query, {"exec_id": execution_id})
                    transaction.commit() # Confirma la transacción
            
            logging.info(f"Solicitud de detención registrada exitosamente para {execution_id}")
            return True
        except Exception as e:
            # La transacción se revierte automáticamente si ocurre una excepción dentro del bloque 'with'.
            logging.error(f"Error al registrar la solicitud de detención para {execution_id}: {e}", exc_info=True)
            return False

