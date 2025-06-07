import jwt
import logging
from fastapi import HTTPException


def verify_token(token: str, secret_key: str, required_claims: list = None, algorithm: str = 'HS256') -> dict:
    """
    Verifies a JWT token and returns its payload.

    Args:
        token: The JWT token string to verify.
        secret_key: The secret key for decoding.
        required_claims: A list of claims that must be present in the token. Defaults to ['exp'].
        algorithm: The signing algorithm.

    Returns:
        The decoded token payload as a dictionary.

    Raises:
        TokenExpiredError: If the token has expired.
        InvalidTokenError: If the token is invalid (e.g., signature mismatch, malformed).
        TokenProcessingError: For any other unexpected errors during token processing.
    """
    if required_claims is None:
        required_claims = ['exp']

    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[algorithm],
            options={"require": required_claims}
        )
        return payload
    except jwt.ExpiredSignatureError as e:
        logging.info(f"Token expired: {str(e)}. Token prefix: {token[:20]}...")
        raise HTTPException(status_code=401, detail="Token has expired") from e
    except jwt.InvalidTokenError as e:
        logging.info(f"Invalid token: {str(e)}. Token prefix: {token[:20]}...")
        raise HTTPException(status_code=401, detail="Invalid token") from e
    except Exception as e:
        logging.info(f"Unexpected error during token decoding: {str(e)}. Token prefix: {token[:20]}...")
        raise HTTPException(status_code=500, detail="An unexpected error occurred during token processing") from e