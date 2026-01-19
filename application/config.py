import os
from dotenv import load_dotenv

load_dotenv()

EVIDENCE_FILE_DIR = os.getenv("EVIDENCE_FILE_DIR")
HOST = os.getenv("HOST")
RESOURCES_DIR = os.getenv("RESOURCES_DIR")
BUILD_CONTEXT_DIR = os.getenv("BUILD_CONTEXT_DIR")
SELENIUM_IMAGE = os.getenv("SELENIUM_IMAGE")
TEST_CASES_DIR = os.getenv("TEST_CASES_DIR")
DB_SERVER_URL = os.getenv("DB_SERVER_URL")
RABBIT_SERVER_URL = os.getenv("RABBIT_SERVER_URL")
REST_API_URL = os.getenv("REST_API_URL")
DATABASE_API_URL = os.getenv("DATABASE_API_URL")
MAIL_API_URL = os.getenv("MAIL_API_URL")
JMS_API_URL = os.getenv("JMS_API_URL")
GDRIVE_API_URL = os.getenv("GDRIVE_API_URL")
ENCRYPTION_SECRET_KEY = os.getenv("ENCRYPTION_SECRET_KEY")