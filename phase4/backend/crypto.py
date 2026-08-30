"""
Small wrapper around Fernet symmetric encryption, used to store pooled
API keys encrypted in SQLite rather than as plaintext.

Generate a key once with:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
and put it in .env as ENCRYPTION_KEY. Losing this key means losing access
to every stored API key, so keep it safe (and out of git).
"""

import os
from cryptography.fernet import Fernet, InvalidToken

_ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
_fernet = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None


def _require_fernet() -> Fernet:
    if _fernet is None:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Generate one with:\n"
            "python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            "and add it to your .env file."
        )
    return _fernet


def encrypt(plaintext: str) -> str:
    return _require_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _require_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Could not decrypt key — wrong ENCRYPTION_KEY?") from exc


def mask(plaintext: str) -> str:
    """For display only — never send full keys to the frontend."""
    if len(plaintext) <= 8:
        return "****"
    return f"{plaintext[:4]}...{plaintext[-4:]}"
