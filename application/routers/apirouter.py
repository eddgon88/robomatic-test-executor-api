from fastapi import APIRouter
import asyncio
from ..jms.jms_client import PikaClient
from ..services.test_executor_service import TestExecutorService
from ..models.models import TestExecutionRequest, StopExecutionRequest
import threading

router = APIRouter(prefix="/test-executor/v1")

@router.on_event("startup")
async def startup():
    print("start")
    loop1 = asyncio.get_running_loop()
    loop2 = asyncio.get_running_loop()
    pikaClient1 = PikaClient(TestExecutorService.executeTest)
    pikaClient2 = PikaClient(TestExecutorService.stop_test)
    task1 = loop1.create_task(pikaClient1.consume_execute_test(loop1))
    task1
    task2 = loop2.create_task(pikaClient2.consume_stop_test_execution(loop2))
    task2

@router.post("/execute", status_code=200)
async def consume(params: TestExecutionRequest):
    threading_execution = threading.Thread(target=TestExecutorService.executeTest, args=(params.dict(),))
    threading_execution.start()
    #TestExecutorService.executeTest(params.dict())
    return True

@router.post("/execution/stop", status_code=200)
async def consume(params: StopExecutionRequest):
    threading_execution = threading.Thread(target=TestExecutorService.stop_test, args=(params.dict(),))
    threading_execution.start()
    #TestExecutorService.stop_test(params.dict())
    return True