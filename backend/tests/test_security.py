import logging

import pytest

from app.security.crypto import CryptoError, FieldCipher, Fingerprinter, new_key
from app.security.masking import MaskingFilter, mask_text, mask_value


def test_sealed_values_open_only_on_their_own_record():
    c = FieldCipher([new_key()])
    blob = c.seal({"email": "jo@example.com"}, "rec-1")
    assert b"jo@example.com" not in blob
    assert c.open(blob, "rec-1") == {"email": "jo@example.com"}
    with pytest.raises(CryptoError):
        c.open(blob, "rec-2")                      # copied onto another row
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(CryptoError):
        c.open(tampered, "rec-1")


def test_keys_rotate_old_values_still_open():
    old, new = new_key(), new_key()
    blob = FieldCipher([old]).seal("x", "r")
    rotated = FieldCipher([new, old])
    assert rotated.open(blob, "r") == "x" and rotated.needs_rotation(blob)
    assert not rotated.needs_rotation(rotated.seal("x", "r"))
    with pytest.raises(CryptoError):
        FieldCipher([new]).open(blob, "r")


def test_bad_keys_are_refused():
    with pytest.raises(ValueError):
        FieldCipher(["not-base64!"])
    with pytest.raises(ValueError):
        FieldCipher(["YWJj"])                       # 3 bytes


def test_fingerprints_ignore_case_and_spaces_and_need_the_key():
    k = new_key()
    a, b = Fingerprinter(k), Fingerprinter(new_key())
    assert a.of("email", " Jo@Example.com") == a.of("email", "jo@example.com")
    assert a.of("email", "jo@example.com") != b.of("email", "jo@example.com")
    assert "jo" not in a.of("email", "jo@example.com")


def test_log_lines_are_masked():
    line = "mapped jo.smith@example.com +44 7700 900123 born 14/03/2008 at LS1 4AP, row 12"
    out = mask_text(line)
    for secret in ("jo.smith", "7700", "14/03/2008", "LS1 4AP"):
        assert secret not in out
    assert "row 12" in out
    assert mask_value("details", {"guardian_name": "Hannah", "fields": ["email"], "count": 3}) == \
        {"guardian_name": "<hidden>", "fields": ["email"], "count": 3}


def test_the_filter_masks_every_record(caplog):
    logger = logging.getLogger("t")
    caplog.handler.addFilter(MaskingFilter())
    with caplog.at_level(logging.INFO):
        logger.info("submitting for %s", "amara@example.com")
    assert "amara@example.com" not in caplog.text and "<email>" in caplog.text
