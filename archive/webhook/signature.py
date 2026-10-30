"""Ed25519 signature helpers for QQ Webhook callbacks."""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SIGNATURE_HEADER = "X-Signature-Ed25519"
TIMESTAMP_HEADER = "X-Signature-Timestamp"


def derive_private_key(secret: str) -> Ed25519PrivateKey:
    """Derive the deterministic Ed25519 key used by QQ from a bot secret.

    QQ repeats the secret until at least 32 bytes are available, then truncates
    the first 32 bytes to form the Ed25519 seed.
    """

    if not secret:
        raise ValueError("secret cannot be empty")
    seed = secret.encode("utf-8")
    while len(seed) < 32:
        seed = seed * 2
    return Ed25519PrivateKey.from_private_bytes(seed[:32])


def sign_bytes(secret: str, message: bytes) -> str:
    """Sign raw bytes and return a lowercase hex signature."""

    signature = derive_private_key(secret).sign(message)
    return signature.hex()


def validation_response(secret: str, plain_token: str, event_ts: str) -> dict[str, str]:
    """Build the response body for an ``op=13`` callback-URL validation.

    The signed message is ``event_ts + plain_token`` exactly as specified by
    the platform.
    """

    message = f"{event_ts}{plain_token}".encode()
    return {"plain_token": plain_token, "signature": sign_bytes(secret, message)}


def verify_webhook_signature(
    secret: str,
    signature_hex: str,
    timestamp: str,
    body: bytes,
) -> bool:
    """Verify the signature of an inbound webhook event.

    Args:
        secret: Bot ClientSecret.
        signature_hex: Value of the ``X-Signature-Ed25519`` header.
        timestamp: Value of the ``X-Signature-Timestamp`` header.
        body: Raw request body.

    Returns:
        ``True`` when the signature is valid, ``False`` otherwise.
    """

    if not signature_hex or not timestamp:
        return False
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    public_key: Ed25519PublicKey = derive_private_key(secret).public_key()
    message = timestamp.encode("utf-8") + body
    try:
        public_key.verify(signature, message)
    except InvalidSignature:
        return False
    return True


__all__ = [
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "derive_private_key",
    "sign_bytes",
    "validation_response",
    "verify_webhook_signature",
]
