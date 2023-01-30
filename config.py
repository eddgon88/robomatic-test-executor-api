# config.py
import os
from dotenv import load_dotenv
from pydantic import BaseSettings

class Settings(BaseSettings):
    evidence_file_dir : str

    class Config:
        env_file = ".env"


