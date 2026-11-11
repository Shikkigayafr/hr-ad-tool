"""Шифрование выданных сотрудникам паролей отдельным ключом."""
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from secret_utils import read_secret


def configure_employee_passwords(app):
    key = read_secret("EMPLOYEE_PASSWORD_KEY")
    if key:
        app.extensions["employee_password_cipher"] = Fernet(key)


def encrypt_issued_password(password):
    cipher = current_app.extensions.get("employee_password_cipher")
    return cipher.encrypt(password.encode()).decode("ascii") if cipher else None


def decrypt_issued_password(token):
    cipher = current_app.extensions.get("employee_password_cipher")
    if cipher is None:
        raise InvalidToken
    return cipher.decrypt(token.encode("ascii")).decode()
