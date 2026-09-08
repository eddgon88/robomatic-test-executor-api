import os
import logging
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

class R2StorageService:
    """
    Servicio de almacenamiento compatible con Cloudflare R2 / AWS S3.
    Maneja subida, descarga y listado de evidencias, casos y credenciales.
    """
    def __init__(self):
        self.endpoint_url = os.getenv("R2_ENDPOINT")
        self.access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = os.getenv("R2_BUCKET_NAME", "robomatic-evidence")
        self.client = None
        self.is_enabled = False

        if self.endpoint_url and self.access_key and self.secret_key:
            try:
                import boto3
                self.client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    region_name="auto"
                )
                self.is_enabled = True
                logging.info(f"R2StorageService inicializado conectado a bucket '{self.bucket_name}' en {self.endpoint_url}")
            except Exception as e:
                logging.warning(f"No se pudo inicializar cliente boto3 para Cloudflare R2: {e}")
        else:
            logging.info("R2StorageService inactivo (variables R2_ENDPOINT/R2_ACCESS_KEY_ID no configuradas). Usando almacenamiento local.")

    def upload_file(self, local_path: str, r2_key: str) -> bool:
        """Sube un archivo local al bucket R2."""
        if not self.is_enabled:
            return False
        try:
            self.client.upload_file(local_path, self.bucket_name, r2_key)
            logging.info(f"Archivo subido exitosamente a R2: {r2_key}")
            return True
        except Exception as e:
            logging.error(f"Error al subir archivo a R2 ({r2_key}): {e}")
            return False

    def upload_bytes(self, data_bytes: bytes, r2_key: str, content_type: str = "application/octet-stream") -> bool:
        """Sube contenido binario/texto directamente a R2."""
        if not self.is_enabled:
            return False
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=r2_key,
                Body=data_bytes,
                ContentType=content_type
            )
            logging.info(f"Bytes subidos exitosamente a R2: {r2_key}")
            return True
        except Exception as e:
            logging.error(f"Error al subir bytes a R2 ({r2_key}): {e}")
            return False

    def get_file_bytes(self, r2_key: str) -> Optional[bytes]:
        """Obtiene el contenido binario de un archivo en R2."""
        if not self.is_enabled:
            return None
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=r2_key)
            return response['Body'].read()
        except Exception as e:
            logging.error(f"Error al leer archivo de R2 ({r2_key}): {e}")
            return None

    def list_files(self, prefix: str = "") -> List[str]:
        """Lista archivos bajo un prefijo (ej: 'evidence/TE123/')."""
        if not self.is_enabled:
            return []
        try:
            response = self.client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)
            if 'Contents' in response:
                return [item['Key'] for item in response['Contents']]
            return []
        except Exception as e:
            logging.error(f"Error al listar archivos en R2 con prefijo '{prefix}': {e}")
            return []
