from fastapi import APIRouter
from ..services.test_executor_service import TestExecutorService
from ..services.docker_service import DockerService
from ..services.execution_service import ExecutionService
from ..models.models import TestExecutionRequest, StopExecutionRequest, ExecutionPorts
import threading

router = APIRouter(prefix="/test-executor/v1")
dockerService = DockerService()

@router.on_event("startup")
async def startup():
    print("start")
    dockerService.createDockerImage()

@router.post("/execute", status_code=200)
async def execute(params: TestExecutionRequest):
    threading_execution = threading.Thread(target=TestExecutorService.executeTest, args=(params.dict(),))
    threading_execution.start()
    #TestExecutorService.executeTest(params.dict())
    return True

@router.post("/execution/stop", status_code=200)
async def stop(params: StopExecutionRequest):
    threading_execution = threading.Thread(target=TestExecutorService.stop_test, args=(params.dict(),))
    threading_execution.start()
    #TestExecutorService.stop_test(params.dict())
    return True

@router.get("/execution/ports/{execution_id}", status_code=200)
async def get_vnc_port(execution_id: str):
    return ExecutionService.get_execution_vnc_port(execution_id)