from fastapi import APIRouter
import asyncio
from ..jms.jms_client import PikaClient
from ..services.test_executor_service import TestExecutorService
from ..services.docker_service import DockerService
from ..models.models import TestExecutionRequest, StopExecutionRequest
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

@router.get("/docker-images", status_code=200)
async def images():
    dockerService.docker_image()
    return True

@router.get("/create-docker", status_code=200)
async def create_docker():
    dockerService.createDocker()
    return True

@router.get("/docker-ps", status_code=200)
async def images():
    dockerService.docker_image()
    return True