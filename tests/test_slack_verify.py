import time

import pytest

from app.services.slack.verify import SignatureError, sign, verify_signature

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
BODY = b"token=x&team_id=T1&event=whatever"


def test_a_genuine_request_verifies():
    ts = str(int(time.time()))
    verify_signature(SECRET, ts, sign(SECRET, ts, BODY), BODY)


def test_rejects_bad_signature():
    ts = str(int(time.time()))
    with pytest.raises(SignatureError):
        verify_signature(SECRET, ts, "v0=deadbeef", BODY)


def test_rejects_a_signature_made_with_another_secret():
    ts = str(int(time.time()))
    forged = sign("attacker-secret", ts, BODY)
    with pytest.raises(SignatureError):
        verify_signature(SECRET, ts, forged, BODY)


def test_rejects_a_tampered_body():
    ts = str(int(time.time()))
    signature = sign(SECRET, ts, BODY)
    with pytest.raises(SignatureError):
        verify_signature(SECRET, ts, signature, BODY + b"&admin=1")


def test_rejects_a_replayed_request_outside_the_window():
    old = str(int(time.time()) - 600)
    with pytest.raises(SignatureError):
        verify_signature(SECRET, old, sign(SECRET, old, BODY), BODY)


def test_accepts_inside_the_window():
    recent = str(int(time.time()) - 60)
    verify_signature(SECRET, recent, sign(SECRET, recent, BODY), BODY)


@pytest.mark.parametrize(("ts", "sig"), [(None, "v0=x"), ("123", None), (None, None)])
def test_missing_headers_are_rejected(ts, sig):
    with pytest.raises(SignatureError):
        verify_signature(SECRET, ts, sig, BODY)


def test_malformed_timestamp_is_rejected():
    with pytest.raises(SignatureError):
        verify_signature(SECRET, "not-a-number", "v0=x", BODY)


def test_unconfigured_secret_fails_closed():
    ts = str(int(time.time()))
    with pytest.raises(SignatureError):
        verify_signature("", ts, sign(SECRET, ts, BODY), BODY)
