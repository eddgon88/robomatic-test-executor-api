import os
from dotenv import load_dotenv

load_dotenv()

EVIDENCE_FILE_DIR = os.getenv("EVIDENCE_FILE_DIR", "/home/evidence")
HOST = os.getenv("HOST", "0.0.0.0")
RESOURCES_DIR = os.getenv("RESOURCES_DIR", "/app/resources")
BUILD_CONTEXT_DIR = os.getenv("BUILD_CONTEXT_DIR", "/app/resources/context")
SELENIUM_IMAGE = os.getenv("SELENIUM_IMAGE", "selenium/standalone-chrome:latest")
TEST_CASES_DIR = os.getenv("TEST_CASES_DIR", "/home/cases/")

# Base de datos: soporta DB_SERVER_URL directa o construcción desde DB_HOST/DB_USER/DB_PWD
DB_SERVER_URL = os.getenv("DB_SERVER_URL")
if not DB_SERVER_URL and os.getenv("DB_HOST"):
    db_user = os.getenv("DB_USER", "neondb_owner")
    db_pwd = os.getenv("DB_PWD") or os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "test_executor")
    DB_SERVER_URL = f"postgresql://{db_user}:{db_pwd}@{db_host}:{db_port}/{db_name}?sslmode=require"
    os.environ["DB_SERVER_URL"] = DB_SERVER_URL

# Mensajería: soporta RABBIT_SERVER_URL o CLOUDAMQP_URL
RABBIT_SERVER_URL = os.getenv("RABBIT_SERVER_URL") or os.getenv("CLOUDAMQP_URL")
if RABBIT_SERVER_URL:
    os.environ["RABBIT_SERVER_URL"] = RABBIT_SERVER_URL

# Browserless / Selenium Standalone en Cloud Run
BROWSERLESS_HOST = os.getenv("BROWSERLESS_HOST")
BROWSERLESS_TOKEN = os.getenv("BROWSERLESS_TOKEN")

REST_API_URL = os.getenv("REST_API_URL")
DATABASE_API_URL = os.getenv("DATABASE_API_URL")
MAIL_API_URL = os.getenv("MAIL_API_URL")
JMS_API_URL = os.getenv("JMS_API_URL")
GDRIVE_API_URL = os.getenv("GDRIVE_API_URL")
AI_API_URL = os.getenv("AI_API_URL", "http://robomatic-ai-api:5009/ai/v1/execute")
ENCRYPTION_SECRET_KEY = os.getenv("ENCRYPTION_SECRET_KEY")

# Cloudflare R2 Object Storage
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "robomatic-evidence")