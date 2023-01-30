from typing import Optional
from pydantic import BaseModel

class TestExecutionRequest(BaseModel):
    script: str
    test_cases_file: str
    threads: int
    name: str
    test_execution_id: str

class StopExecutionRequest(BaseModel):
    id: int
    test_results_dir: str
    test_id: int
    status: int
    test_execution_id: str