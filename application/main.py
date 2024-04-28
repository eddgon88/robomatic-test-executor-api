# application/__init__.py
from fastapi import FastAPI, Depends
from .routers import apirouter
from . import config
from functools import lru_cache

app_configs = {"title": "test-executor-api",
               "EVIDENCE_FILE_DIR": config.EVIDENCE_FILE_DIR,
               "HOST": config.HOST,}

def create_app():
    app = FastAPI(**app_configs)
    app.include_router(apirouter.router)
    return app
