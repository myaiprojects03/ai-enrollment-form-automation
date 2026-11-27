"""Print fresh secrets for .env: ENCRYPTION_KEYS, FINGERPRINT_KEY, OPERATOR_TOKEN and SESSION_SECRET.

    python -m scripts.keys
"""
import secrets

from app.security.crypto import new_key

if __name__ == "__main__":
    print(f"ENCRYPTION_KEYS={new_key()}")
    print(f"FINGERPRINT_KEY={new_key()}")
    print(f"OPERATOR_TOKEN={secrets.token_urlsafe(32)}")
    print(f"SESSION_SECRET={secrets.token_urlsafe(32)}")
