"""Generate an RS256 signing key pair for local development.

    python scripts/generate_keys.py            # writes keys/private.pem + keys/public.pem
    python scripts/generate_keys.py --kid 2026-08-01 --out keys/next

Production keys are NOT produced this way: they are created inside the secrets
vault and mounted read-only into the container, so the private key never
touches a developer machine or an image layer (architecture §9.1).

Rotation (architecture §5) works by generating a second pair, pointing
`JWT_PRIVATE_KEY_PATH` / `JWT_ACTIVE_KID` at the new one and moving the old
public key to `JWT_PREVIOUS_PUBLIC_KEY_PATH` / `JWT_PREVIOUS_KID`. Both keys
are then served from JWKS, so tokens signed before the switch keep verifying
until they expire.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate(out_dir: Path, kid: str, *, force: bool) -> None:
    private_path = out_dir / "private.pem"
    public_path = out_dir / "public.pem"

    existing = [p for p in (private_path, public_path) if p.exists()]
    if existing and not force:
        raise SystemExit(
            f"{', '.join(str(p) for p in existing)} already exist(s). "
            "Re-run with --force to overwrite — every token signed by the old "
            "key stops verifying the moment it is replaced.",
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    # 2048 bits is the JWA floor for RS256 and what every JWT library expects
    # to handle; 4096 buys little here and slows each signature down.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )

    print(f"wrote {private_path}")
    print(f"wrote {public_path}")
    print()
    print("Add to your .env:")
    print(f"  JWT_PRIVATE_KEY_PATH={private_path.as_posix()}")
    print(f"  JWT_PUBLIC_KEY_PATH={public_path.as_posix()}")
    print(f"  JWT_ACTIVE_KID={kid}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="keys", help="output directory (default: keys)")
    parser.add_argument(
        "--kid",
        default=f"dev-{datetime.now(UTC):%Y-%m-%d}",
        help="key id to advertise in JWKS and in the JWT header",
    )
    parser.add_argument("--force", action="store_true", help="overwrite an existing pair")
    args = parser.parse_args()

    generate(Path(args.out), args.kid, force=args.force)


if __name__ == "__main__":
    main()
