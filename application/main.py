# application/__init__.py
from fastapi import FastAPI, Depends
from .routers import apirouter
import config
from functools import lru_cache

@lru_cache()
def get_settings():
    return config.Settings()

settings: config.Settings = Depends(get_settings)

def create_app():
    app = FastAPI()
    app.include_router(apirouter.router)
    return app
