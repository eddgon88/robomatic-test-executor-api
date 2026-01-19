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
               "RABBIT_SERVER_URL": config.RABBIT_SERVER_URL,
               "REST_API_URL": config.REST_API_URL,
               "DATABASE_API_URL": config.DATABASE_API_URL,
               "MAIL_API_URL": config.MAIL_API_URL,
               "JMS_API_URL": config.JMS_API_URL,
               "GDRIVE_API_URL": config.GDRIVE_API_URL,
               "ENCRYPTION_SECRET_KEY": config.ENCRYPTION_SECRET_KEY}

def create_app():
    app = FastAPI(**app_configs)
    app.include_router(apirouter.router)
    return app
