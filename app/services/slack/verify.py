import hashlib
import hmac
import time

# PRD section 16: signature verification with a 5 minute timestamp window.
# Threat: forged Slack requests. Test: test_rejects_bad_signature.

VERSION = "v0"
MAX_SKEW_SECONDS = 60 * 5


class SignatureError(Exception):
    pass


def sign(signing_secret: str, timestamp: str, body: bytes) -> str:
    basestring = f"{VERSION}:{timestamp}:".encode() + body
    digest = hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return f"{VERSION}={digest}"


def verify_signature(
    signing_secret: str,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    *,
    now: float | None = None,
) -> None:
    """Raise SignatureError unless the request is genuinely from Slack and recent.

    Replay protection is the timestamp window; payload-level replay is handled
    separately by processed_event and processed_interaction.
    """
    if not signing_secret:
        raise SignatureError("signing secret not configured")
    if not timestamp or not signature:
        raise SignatureError("missing signature headers")

    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise SignatureError("malformed timestamp") from exc

    current = now if now is not None else time.time()
    if abs(current - sent_at) > MAX_SKEW_SECONDS:
        raise SignatureError("timestamp outside the replay window")

    expected = sign(signing_secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("signature mismatch")
