from pydantic import BaseModel

class TestExecutionRequest(BaseModel):
    script: str
    before_script: str
    after_script: str
    test_cases_file: str
    threads: int
    name: str
    test_execution_id: str
    web: bool

class StopExecutionRequest(BaseModel):
    id: int
    test_results_dir: str
    test_id: int
    status: int
    test_execution_id: str

class ExecutionPorts(BaseModel):
    id: int
    execution_id: str
    selenium_port: str
    vnc_port: str