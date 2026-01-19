import base64
import os
import logging
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format='(%(threadName)-10s) [%(levelname)s] %(message)s',)

# Constantes que deben coincidir con el servicio de encriptación en Java
SALT_LENGTH = 16
GCM_IV_LENGTH = 12
KEY_LENGTH = 32  # 256 bits
ITERATIONS = 65536

# Tipos de credenciales
CREDENTIAL_TYPE_PASSWORD = 1
CREDENTIAL_TYPE_CERTIFICATE = 2


class CredentialService:
    """
    Servicio para desencriptar credenciales usando AES-256-GCM.
    Compatible con CredentialEncryptionService de robomatic-core.
    """

    def __init__(self, credentials: list = None):
        """
        Inicializa el servicio con una lista de credenciales.
        
        Args:
            credentials: Lista de diccionarios con las credenciales del test
        """
        self.secret_key = os.getenv('ENCRYPTION_SECRET_KEY', 'robomatic-default-secret-key-2024')
        self.credentials = {}
        
        if credentials:
            for cred in credentials:
                cred_name = cred.get('name')
                logging.info(f"Loading credential: {cred_name}")
                self.credentials[cred_name] = cred
            logging.info(f"Loaded credentials: {list(self.credentials.keys())}")
        else:
            logging.warning("No credentials provided to CredentialService")

    def get_credential(self, name: str) -> str:
        """
        Obtiene el valor de una credencial por su nombre.
        
        Para passwords: desencripta y retorna el valor
        Para certificados: retorna la ruta del archivo
        
        Args:
            name: Nombre/alias de la credencial
            
        Returns:
            Valor desencriptado (password) o ruta del archivo (certificado)
        """
        if name not in self.credentials:
            raise Exception(f"Credential not found: {name}")
        
        cred = self.credentials[name]
        credential_type = cred.get('credential_type_id') or cred.get('credentialTypeId')
        
        if credential_type == CREDENTIAL_TYPE_PASSWORD:
            encrypted_value = cred.get('encrypted_value') or cred.get('encryptedValue')
            if not encrypted_value:
                raise Exception(f"No encrypted value for credential: {name}")
            return self.decrypt(encrypted_value)
        
        elif credential_type == CREDENTIAL_TYPE_CERTIFICATE:
            file_path = cred.get('file_path') or cred.get('filePath')
            if not file_path:
                raise Exception(f"No file path for certificate: {name}")
            return file_path
        
        else:
            raise Exception(f"Unknown credential type: {credential_type}")

    def decrypt(self, encrypted_text: str) -> str:
        """
        Desencripta un valor encriptado con AES-256-GCM.
        
        El formato del texto encriptado es: Base64(salt + iv + ciphertext)
        
        Args:
            encrypted_text: Texto encriptado en Base64
            
        Returns:
            Texto desencriptado
        """
        try:
            # Decodificar Base64
            decoded = base64.b64decode(encrypted_text)
            
            # Extraer componentes
            salt = decoded[:SALT_LENGTH]
            iv = decoded[SALT_LENGTH:SALT_LENGTH + GCM_IV_LENGTH]
            ciphertext = decoded[SALT_LENGTH + GCM_IV_LENGTH:]
            
            # Derivar clave usando PBKDF2
            key = self._derive_key(self.secret_key, salt)
            
            # Desencriptar usando AES-GCM
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(iv, ciphertext, None)
            
            return plaintext.decode('utf-8')
            
        except Exception as e:
            logging.error(f"Error decrypting value: {e}")
            raise Exception(f"Error decrypting credential: {e}")

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """
        Deriva una clave AES-256 desde la contraseña usando PBKDF2.
        
        Args:
            password: Contraseña maestra
            salt: Salt aleatorio
            
        Returns:
            Clave derivada de 256 bits
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH,
            salt=salt,
            iterations=ITERATIONS,
            backend=default_backend()
        )
        return kdf.derive(password.encode('utf-8'))


