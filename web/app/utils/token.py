import jwt
from datetime import datetime, timedelta, timezone


def generate_token(secret_key, payload: dict = None, ttl_seconds: int = 3600, algorithm: str = 'HS256') -> str:
    """
    Generates a JWT token.

    Args:
        secret_key: The secret key for encoding.
        payload: A dictionary containing the claims to include in the token.
        ttl_hours: Time to live for the token in hours.
        algorithm: The signing algorithm.

    Returns:
        The encoded JWT token string.
    """
    if payload is None:
        payload = {}

    token_payload = {
        **payload,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    }
    token = jwt.encode(
        token_payload,
        secret_key,
        algorithm=algorithm
    )
    return token