"""RSA key material: loading, and the JWK projection served at
`/.well-known/jwks.json`.

Architecture §5 in one place:
  * only DiddiFreeID holds the private key, so only DiddiFreeID can mint a
    token — a compromised consumer module cannot forge one, which is the whole
    reason RS256 was chosen over HS256;
  * two keys can be valid at once. During a rotation the new key signs while
    the previous one stays published, so tokens issued before the switch keep
    verifying in every module until they expire, and nobody is logged out;
  * consumers pick the right key by the `kid` carried in the JWT header.

The key ring is loaded once, lazily, and cached — reading two PEM files on
every JWKS request would be pointless I/O, and the JWKS endpoint is polled by
every module in the ecosystem.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from identity_app.core.settings import settings

logger = logging.getLogger(__name__)


def _b64url_uint(value: int) -> str:
    """Encode an RSA parameter the way RFC 7518 §6.3 requires: big-endian,
    minimum length, base64url, no padding."""
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _read(path_str: str, *, what: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        raise RuntimeError(
            f"{what} introuvable : {path}. "
            "Générez une paire de développement avec `python scripts/generate_keys.py`, "
            "ou montez les clés du coffre-fort en production.",
        )
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class PublicKeyEntry:
    """One published verification key."""

    kid: str
    pem: str

    def to_jwk(self) -> dict:
        public_key = serialization.load_pem_public_key(self.pem.encode())
        if not isinstance(public_key, RSAPublicKey):
            raise RuntimeError(f"La clé publique {self.kid} n'est pas une clé RSA.")
        numbers = public_key.public_numbers()
        return {
            "kid": self.kid,
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "n": _b64url_uint(numbers.n),
            "e": _b64url_uint(numbers.e),
        }


@dataclass(frozen=True)
class KeyRing:
    active_kid: str
    private_pem: str
    public_keys: tuple[PublicKeyEntry, ...]

    def jwks(self) -> dict:
        """The document served at `/.well-known/jwks.json`.

        The active key is listed first. That is cosmetic for a correct client —
        the contract tells consumers to select by `kid` — but it makes the
        response readable when someone curls it during an incident.
        """
        return {"keys": [entry.to_jwk() for entry in self.public_keys]}


@lru_cache(maxsize=1)
def get_key_ring() -> KeyRing:
    """Load the key ring from the configured paths. Cached for the process
    lifetime; a rotation is a config change plus a restart, not a hot reload —
    which is deliberate, since two processes disagreeing about which key is
    active would be far harder to debug than a rolling restart."""
    private_pem = _read(settings.jwt_private_key_path, what="Clé privée de signature")
    public_pem = _read(settings.jwt_public_key_path, what="Clé publique de signature")

    entries = [PublicKeyEntry(kid=settings.jwt_active_kid, pem=public_pem)]

    previous_path = settings.jwt_previous_public_key_path
    previous_kid = settings.jwt_previous_kid
    if previous_path and previous_kid:
        entries.append(
            PublicKeyEntry(
                kid=previous_kid,
                pem=_read(previous_path, what="Clé publique précédente"),
            ),
        )
        logger.info("rotation en cours : kid actif=%s, kid précédent=%s", settings.jwt_active_kid, previous_kid)
    elif previous_path or previous_kid:
        # Half-configured rotation: publishing a key without its id (or the
        # reverse) silently breaks verification for every token signed by it.
        raise RuntimeError(
            "Rotation mal configurée : JWT_PREVIOUS_PUBLIC_KEY_PATH et JWT_PREVIOUS_KID "
            "doivent être renseignés ensemble, ou tous les deux vides.",
        )

    return KeyRing(
        active_kid=settings.jwt_active_kid,
        private_pem=private_pem,
        public_keys=tuple(entries),
    )
