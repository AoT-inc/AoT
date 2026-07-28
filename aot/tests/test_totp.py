# coding=utf-8
"""aot.utils.totp 검증 — RFC 6238 부록 B 공식 테스트 벡터 포함.

이 파일의 핵심은 RFC 벡터 테스트다. 인증 코드를 라이브러리 없이 구현했으므로,
표준 명세와 바이트 단위로 일치한다는 증거가 있어야 한다.
"""
import base64
import hashlib

import pytest

from aot.utils.totp import (generate_secret, get_totp_token, provisioning_uri,
                            verify_totp)

# RFC 6238 Appendix B: seed 는 ASCII "12345678901234567890" 을 알고리즘별
# 키 길이(20/32/64바이트)만큼 이어붙인 값이다.
_SEED_SHA1 = base64.b32encode(b"12345678901234567890").decode()
_SEED_SHA256 = base64.b32encode(b"12345678901234567890123456789012").decode()
_SEED_SHA512 = base64.b32encode(
    b"1234567890123456789012345678901234567890123456789012345678901234").decode()


class TestRFC6238Vectors:
    """RFC 6238 Appendix B 의 공식 테스트 벡터.

    벡터는 8자리(digits=8) 기준으로 표기돼 있다.
    """

    @pytest.mark.parametrize("timestamp,expected", [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ])
    def test_sha1_vectors(self, timestamp, expected):
        assert get_totp_token(_SEED_SHA1, at_time=timestamp, digits=8,
                              digest=hashlib.sha1) == expected

    @pytest.mark.parametrize("timestamp,expected", [
        (59, "46119246"),
        (1111111109, "68084774"),
        (1111111111, "67062674"),
        (1234567890, "91819424"),
        (2000000000, "90698825"),
        (20000000000, "77737706"),
    ])
    def test_sha256_vectors(self, timestamp, expected):
        assert get_totp_token(_SEED_SHA256, at_time=timestamp, digits=8,
                              digest=hashlib.sha256) == expected

    @pytest.mark.parametrize("timestamp,expected", [
        (59, "90693936"),
        (1111111109, "25091201"),
        (1111111111, "99943326"),
        (1234567890, "93441116"),
        (2000000000, "38618901"),
        (20000000000, "47863826"),
    ])
    def test_sha512_vectors(self, timestamp, expected):
        assert get_totp_token(_SEED_SHA512, at_time=timestamp, digits=8,
                              digest=hashlib.sha512) == expected


class TestSecretGeneration:
    def test_secret_is_base32_and_long_enough(self):
        secret = generate_secret()
        # RFC 4226: 최소 128비트, 권장 160비트 -> 20바이트 -> base32 32자
        assert len(secret) >= 32
        base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)

    def test_secrets_differ(self):
        assert generate_secret() != generate_secret()

    def test_generated_secret_round_trips(self):
        """패딩을 떼고 저장하므로 다시 쓸 때 복원되는지 확인."""
        secret = generate_secret()
        token = get_totp_token(secret, at_time=1234567890)
        assert verify_totp(secret, token, at_time=1234567890)


class TestVerification:
    SECRET = _SEED_SHA1

    def test_accepts_current_code(self):
        token = get_totp_token(self.SECRET, at_time=1234567890)
        assert verify_totp(self.SECRET, token, at_time=1234567890)

    def test_rejects_wrong_code(self):
        assert not verify_totp(self.SECRET, "000000", at_time=1234567890)

    def test_accepts_previous_step_for_clock_skew(self):
        """기기 시계가 30초 느린 경우."""
        token = get_totp_token(self.SECRET, at_time=1234567890 - 30)
        assert verify_totp(self.SECRET, token, at_time=1234567890)

    def test_accepts_next_step_for_clock_skew(self):
        token = get_totp_token(self.SECRET, at_time=1234567890 + 30)
        assert verify_totp(self.SECRET, token, at_time=1234567890)

    def test_rejects_code_outside_window(self):
        """2스텝(60초) 벗어난 코드는 거부 — 유효창을 넓히지 않는다."""
        token = get_totp_token(self.SECRET, at_time=1234567890 - 120)
        assert not verify_totp(self.SECRET, token, at_time=1234567890)

    @pytest.mark.parametrize("bad", ["", None, "12345", "1234567", "abcdef", "12 34 56"])
    def test_rejects_malformed_input(self, bad):
        assert not verify_totp(self.SECRET, bad, at_time=1234567890)

    def test_rejects_when_no_secret(self):
        assert not verify_totp(None, "123456", at_time=1234567890)
        assert not verify_totp("", "123456", at_time=1234567890)

    def test_whitespace_in_user_input_tolerated(self):
        """인증 앱이 '123 456' 처럼 띄어 보여주는 경우가 있다."""
        token = get_totp_token(self.SECRET, at_time=1234567890)
        spaced = token[:3] + ' ' + token[3:]
        assert verify_totp(self.SECRET, spaced, at_time=1234567890)

    def test_invalid_secret_does_not_raise(self):
        """DB 값이 손상돼도 예외 대신 인증 실패로 처리돼야 한다."""
        assert not verify_totp("!!!not-base32!!!", "123456", at_time=1234567890)


class TestProvisioningURI:
    def test_contains_required_parts(self):
        uri = provisioning_uri("ABCDEFGHIJKLMNOP", "admin")
        assert uri.startswith("otpauth://totp/")
        assert "secret=ABCDEFGHIJKLMNOP" in uri
        assert "issuer=AoT" in uri
        assert "period=30" in uri
        assert "digits=6" in uri
