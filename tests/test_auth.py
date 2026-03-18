"""Tests for Kalshi API authentication."""

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

from kalshi_bot.api.auth import sign_request


def _generate_test_key() -> rsa.RSAPrivateKey:
    """Generate a test RSA key pair."""
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )


class TestSignRequest:
    def test_returns_required_headers(self):
        """Signature should include timestamp and signature headers."""
        key = _generate_test_key()
        headers = sign_request(key, "GET", "/trade-api/v2/markets", timestamp_ms=1234567890000)

        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers
        assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1234567890000"

    def test_signature_is_base64(self):
        """Signature should be valid base64."""
        import base64
        key = _generate_test_key()
        headers = sign_request(key, "GET", "/trade-api/v2/markets")
        sig_bytes = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        assert len(sig_bytes) > 0

    def test_signature_is_verifiable(self):
        """Signature should verify with the corresponding public key."""
        import base64
        key = _generate_test_key()
        pub = key.public_key()

        ts = 1700000000000
        method = "POST"
        path = "/trade-api/v2/portfolio/orders"

        headers = sign_request(key, method, path, timestamp_ms=ts)
        sig = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        message = f"{ts}{method.upper()}{path}".encode()

        # Should not raise
        pub.verify(
            sig,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_different_methods_produce_different_signatures(self):
        """GET and POST should produce different signatures."""
        key = _generate_test_key()
        ts = 1700000000000
        path = "/trade-api/v2/markets"

        h1 = sign_request(key, "GET", path, timestamp_ms=ts)
        h2 = sign_request(key, "POST", path, timestamp_ms=ts)

        assert h1["KALSHI-ACCESS-SIGNATURE"] != h2["KALSHI-ACCESS-SIGNATURE"]

    def test_different_timestamps_produce_different_signatures(self):
        """Different timestamps should produce different signatures."""
        key = _generate_test_key()
        path = "/trade-api/v2/markets"

        h1 = sign_request(key, "GET", path, timestamp_ms=1000)
        h2 = sign_request(key, "GET", path, timestamp_ms=2000)

        assert h1["KALSHI-ACCESS-SIGNATURE"] != h2["KALSHI-ACCESS-SIGNATURE"]
