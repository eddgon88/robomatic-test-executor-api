# application/__init__.py
from fastapi import FastAPI
from .routers import apirouter
from . import config

app_configs = {"title": "test-executor-api",
               "EVIDENCE_FILE_DIR": config.EVIDENCE_FILE_DIR,
               "HOST": config.HOST,
               "RESOURCES_DIR": config.RESOURCES_DIR,
               "BUILD_CONTEXT_DIR": config.BUILD_CONTEXT_DIR,
               "SELENIUM_IMAGE": config.SELENIUM_IMAGE,
               "TEST_CASES_DIR": config.TEST_CASES_DIR,
               "DB_SERVER_URL": config.DB_SERVER_URL,
               "RABBIT_SERVER_URL": config.RABBIT_SERVER_URL}

def create_app():
    app = FastAPI(**app_configs)
    app.include_router(apirouter.router)
    return app
