"""Проверка входных данных и мелкие утилиты без привязки к Flask."""
import re
import secrets

LOGIN_RE = re.compile(r"^[a-zA-Z0-9._-]{3,20}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
NAME_RE = re.compile(r"^[\w .'-]+$")


def password_error(password):
    """Те же правила, что и на фронтенде. None — пароль подходит."""
    if (not password or len(password) < 8 or not re.search(r"[A-Z]", password)
            or not re.search(r"[0-9]", password) or not re.search(r"[^A-Za-z0-9]", password)):
        return "Пароль слишком простой: нужны 8+ символов, заглавная буква, цифра и спецсимвол"
    return None


def generate_password(length: int = 14) -> str:
    """Случайный пароль, проходящий password_error (без похожих символов 0/O, 1/l/I)."""
    lower, upper, digits, special = "abcdefghjkmnpqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789", "!@#$%&*?-_=+"
    alphabet = lower + upper + digits + special
    chars = [secrets.choice(lower), secrets.choice(upper), secrets.choice(digits), secrets.choice(special)]
    chars += [secrets.choice(alphabet) for _ in range(max(length, 8) - 4)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def csv_safe(value):
    """Защита от формул в Excel (=, +, -, @ в начале ячейки)."""
    value = "" if value is None else str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value
