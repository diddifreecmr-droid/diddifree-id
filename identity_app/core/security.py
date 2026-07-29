"""Hashing primitives shared by the whole service.

Two different problems, two different tools:

  * **OTP codes** — six digits, i.e. a keyspace of one million. A plain SHA-256
    of such a code is reversible in milliseconds, so a database dump would hand
    an attacker every in-flight code. Hashing is therefore keyed (HMAC) with a
    server-side pepper that lives in configuration, never in the database: the
    dump alone is useless. Architecture §8 asks for OTP codes to be hashed;
    this is that requirement done in a way that actually holds.

  * **Passwords** — Argon2id, explicitly, not bcrypt (architecture §8).
    Memory-hard, so GPU cracking gains far less than it does against bcrypt.
    Passwords are optional today (`password_hash` is nullable, OTP is the only
    live flow) but the back-office need is already named in contract §5.
"""

from __future__ import annotations

import hmac
from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from identity_app.core.settings import settings

# Defaults follow argon2-cffi's recommended profile; they are a deliberate
# time/memory trade-off and should only be raised, never lowered.
_password_hasher = PasswordHasher()


def hash_otp_code(code: str) -> str:
    return hmac.new(
        settings.otp_hash_pepper.encode(),
        code.encode(),
        sha256,
    ).hexdigest()


def verify_otp_code(code: str, expected_hash: str) -> bool:
    """Constant-time comparison — a timing difference here would let an
    attacker narrow a code digit by digit instead of guessing all six."""
    return hmac.compare_digest(hash_otp_code(code), expected_hash)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
