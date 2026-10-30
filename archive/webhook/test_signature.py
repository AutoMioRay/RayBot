from __future__ import annotations

from qqbot_toolkit.gateway.signature import (
    sign_bytes,
    validation_response,
    verify_webhook_signature,
)

SECRET = "DG5g3B4j9X2KOErG"
PLAIN_TOKEN = "Arq0D5A61EgUu4OxUvOp"
EVENT_TS = "1725442341"
EXPECTED = (
    "87befc99c42c651b3aac0278e71ada338433ae26fcb24307bdc5ad38c1adc2d0"
    "1bcfcadc0842edac85e85205028a1132afe09280305f13aa6909ffc2d652c706"
)


def test_validation_signature_matches_official_vector() -> None:
    response = validation_response(SECRET, PLAIN_TOKEN, EVENT_TS)
    assert response == {"plain_token": PLAIN_TOKEN, "signature": EXPECTED}


def test_webhook_signature_round_trip() -> None:
    body = b'{"op":0,"t":"C2C_MESSAGE_CREATE","d":{}}'
    timestamp = "1725442341"
    signature = sign_bytes(SECRET, timestamp.encode() + body)

    assert verify_webhook_signature(SECRET, signature, timestamp, body)
    assert not verify_webhook_signature(SECRET, signature, timestamp, body + b" ")
    assert not verify_webhook_signature("other-secret", signature, timestamp, body)
    assert not verify_webhook_signature(SECRET, "not-hex", timestamp, body)
