import jwt
import time
from django.conf import settings

def generate_centrifugo_token(user_id, ttl=3600):
    """
    Generates a JWT token for Centrifugo authentication.
    """
    claims = {
        "sub": str(user_id),  # The unique ID of the candidate/user
        "exp": int(time.time()) + ttl, # Token expiry (default 1 hour)
    }
    return jwt.encode(claims, settings.CENTRIFUGO_SECRET, algorithm="HS256")