"""Kalshi API authentication — RSA-PSS request signing."""

from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def load_private_key(path: Path) -> rsa.RSAPrivateKey:
    """Load an RSA private key from a PEM file."""
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError(f"Expected RSA private key, got {type(key).__name__}")
    return key


def sign_request(
    private_key: rsa.RSAPrivateKey,
    method: str,
    path: str,
    timestamp_ms: int | None = None,
) -> dict[str, str]:
    """Generate Kalshi auth headers for a request.

    Signs ``f"{timestamp_ms}{METHOD}{path}"`` with RSA-PSS / SHA-256.

    Returns a dict with the three required headers:
      KALSHI-ACCESS-KEY, KALSHI-ACCESS-TIMESTAMP, KALSHI-ACCESS-SIGNATURE
    """
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    signing_path = path.split("?")[0]
    message = f"{timestamp_ms}{method.upper()}{signing_path}".encode()

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )

    return {
        "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
    }
