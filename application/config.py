import os
from dotenv import load_dotenv

load_dotenv()

EVIDENCE_FILE_DIR = os.getenv("EVIDENCE_FILE_DIR")
HOST = os.getenv("HOST")
