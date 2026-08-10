from cryptography.fernet import Fernet
from django.conf import settings

cipher = Fernet(settings.ENCRYPTION_KEY.encode())

def encrypt_password(password):
    """
    Encrypt a plain text password.
    """
    return cipher.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password):
    """
    Decrypt an encrypted password.
    """
    return cipher.decrypt(encrypted_password.encode()).decode()