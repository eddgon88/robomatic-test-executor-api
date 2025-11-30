from fastapi import APIRouter
#from ..services.test_executor_service import TestExecutorService
from ..services.test_executor_service_v2 import TestExecutorService
from ..services.docker_service import DockerService
from ..services.execution_service import ExecutionService
from ..models.models import TestExecutionRequest, StopExecutionRequest, ExecutionPorts
import threading
import logging

logging.basicConfig(level=logging.INFO,
                    format='(%(threadName)-10s) %(message)s',)

router = APIRouter(prefix="/test-executor/v1")
dockerService = DockerService()

@router.on_event("startup")
async def startup():
    print("start")
    dockerService.createDockerImage()

@router.post("/execute", status_code=200)
async def execute(params: TestExecutionRequest):
    #threading_execution = threading.Thread(target=TestExecutorService.executeTest, args=(params.dict(),))
    #threading_execution.start()
    ##TestExecutorService.executeTest(params.dict())
    #return True
    # 1. Crea una INSTANCIA del servicio para esta ejecución específica.
    test_executor_instance = TestExecutorService(params.dict())

    # 2. El 'target' del hilo es ahora el método 'run' de la INSTANCIA.
    #    No se pasan argumentos porque la instancia ya tiene toda la configuración.
    execution_thread = threading.Thread(target=test_executor_instance.run)
    execution_thread.start()
    
    logging.info(f"Iniciada la ejecución en un nuevo hilo para la solicitud: {params.dict().get('test_execution_id')}")
    return True

@router.post("/execution/stop", status_code=200)
async def stop(params: StopExecutionRequest):
    # Aquí se crea una instancia del servicio de ejecución.
    executor_service = ExecutionService()
    # Se utiliza el método 'stop_test' de la instancia para detener la ejecución.
    logging.info(f"Deteniendo la ejecución con ID: {params.test_execution_id}")
    threading_execution = threading.Thread(target=executor_service.stop_test, args=(params.dict(),))
    threading_execution.start()
    return True

@router.get("/execution/ports/{execution_id}", status_code=200)
async def get_vnc_port(execution_id: str):
    # Aquí se crea una instancia del servicio de ejecución.
    executor_service = ExecutionService() 
    return executor_service.get_execution_vnc_port(execution_id)