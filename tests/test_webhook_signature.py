"""Security-critical: HMAC-SHA256 webhook signature verification.

If this breaks, any unauthenticated caller can push fake calls into
the pipeline and burn Claude API credits.
"""

import hashlib
import hmac

from app.webhooks.ghl import _verify_signature
from config import settings


def _sign(body: bytes, secret: str | None = None) -> str:
    return hmac.new(
        (secret or settings.webhook_secret).encode(),
        body,
        hashlib.sha256,
    ).hexdigest()


class TestVerifySignature:
    def test_valid_signature_accepted(self):
        body = b'{"messageId": "abc123"}'
        sig = _sign(body)
        assert _verify_signature(body, sig) is True

    def test_invalid_signature_rejected(self):
        body = b'{"messageId": "abc123"}'
        assert _verify_signature(body, "deadbeef") is False

    def test_tampered_body_rejected(self):
        body = b'{"messageId": "abc123"}'
        sig = _sign(body)
        tampered = b'{"messageId": "xyz999"}'
        assert _verify_signature(tampered, sig) is False

    def test_empty_signature_rejected(self):
        body = b'{"messageId": "abc123"}'
        assert _verify_signature(body, "") is False

    def test_wrong_secret_rejected(self):
        body = b'{"messageId": "abc123"}'
        sig = _sign(body, secret="wrong-secret")
        assert _verify_signature(body, sig) is False

    def test_empty_body_with_valid_signature(self):
        body = b""
        sig = _sign(body)
        assert _verify_signature(body, sig) is True
