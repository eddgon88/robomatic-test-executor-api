from fastapi import APIRouter, HTTPException, Depends
from ..services.test_executor_service_v2 import TestExecutorService
from ..services.docker_service_v2 import DockerService
from ..services.execution_service_v2 import ExecutionService
from ..models.models import TestExecutionRequest, StopExecutionRequest, ExecutionPorts
import threading
import logging

# Configura el logging en el punto de entrada principal (por ejemplo, main.py)
# Aquí solo obtenemos el logger configurado.
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/test-executor/v1",
    tags=["Test Execution"] # Es una buena práctica etiquetar tus routers
)

# ==============================================================================
# Inyección de Dependencias de FastAPI
# ==============================================================================
# FastAPI puede gestionar el ciclo de vida de nuestras instancias de servicio.
# Esto es más avanzado pero es el "modo FastAPI" de hacer las cosas.
# Por ahora, instanciar manualmente como lo hacemos abajo está perfectamente bien.

def get_execution_service():
    """Esta función 'dependencia' crea una instancia de ExecutionService por cada petición."""
    return ExecutionService()

# ==============================================================================
# Eventos del Ciclo de Vida de la Aplicación
# ==============================================================================

@router.on_event("startup")
async def startup_event():
    """
    Se ejecuta una sola vez cuando la aplicación FastAPI se inicia.
    Ideal para tareas de inicialización como construir una imagen de Docker si no existe.
    """
    logger.info("Application startup: Initializing services...")
    # Es mejor instanciar aquí para usarlo en el evento de inicio.
    docker_service = DockerService()
    # Descomenta la siguiente línea si necesitas construir la imagen al iniciar.
    docker_service.create_docker_image() # Asumiendo que este método existe en tu clase refactorizada
    logger.info("Startup tasks completed.")

# ==============================================================================
# Endpoints de la API
# ==============================================================================

@router.post("/execute", status_code=202) # 202 Accepted es más apropiado para tareas en segundo plano
async def execute(params: TestExecutionRequest):
    """
    Inicia una nueva ejecución de prueba en un hilo separado.
    Responde inmediatamente para no bloquear al cliente.
    """
    logger.info(f"Received request to execute test: {params.test_execution_id}")
    try:
        # 1. Crea una INSTANCIA del servicio para esta ejecución específica.
        test_executor_instance = TestExecutorService(params.dict())

        # 2. El 'target' del hilo es ahora el método 'run' de la INSTANCIA.
        execution_thread = threading.Thread(
            target=test_executor_instance.run,
            name=f"ExecThread-{params.test_execution_id}" # Asignar un nombre al hilo ayuda a depurar
        )
        execution_thread.start()
        
        logger.info(f"Execution thread started for {params.test_execution_id}")
        return {"message": "Test execution has been accepted and is running in the background.", "execution_id": params.test_execution_id}
    except Exception as e:
        logger.error(f"Failed to start execution thread for {params.test_execution_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to initialize the test execution process.")


@router.post("/execution/stop", status_code=200)
async def stop(params: StopExecutionRequest, exec_service: ExecutionService = Depends(get_execution_service)):
    """
    Registra una solicitud para detener una ejecución de prueba en curso.
    Utiliza la instancia refactorizada de ExecutionService.
    """
    logger.info(f"Received request to stop test: {params.test_execution_id}")
    
    # Llama al método de la INSTANCIA del servicio.
    success = exec_service.stop_test(params.test_execution_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to register the stop request for the test execution.")
    
    return {"message": "Stop request registered successfully.", "execution_id": params.test_execution_id}


@router.get("/execution/ports/{execution_id}", response_model=ExecutionPorts)
async def get_vnc_port(execution_id: str, exec_service: ExecutionService = Depends(get_execution_service)):
    """
    Obtiene los puertos VNC y Selenium para una ejecución específica.
    Utiliza la instancia refactorizada de ExecutionService.
    """
    logger.info(f"Fetching ports for execution: {execution_id}")
    
    # Llama al método de la INSTANCIA del servicio.
    ports = exec_service.get_execution_vnc_port(execution_id)
    
    if not ports:
        raise HTTPException(
            status_code=404,
            detail=f"Execution with ID '{execution_id}' not found or has no associated ports."
        )
        
    return ports
