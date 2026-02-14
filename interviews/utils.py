import jwt
import time
from django.conf import settings

def generate_centrifugo_token(user_id, ttl=3600):
    """
    Generates a JWT token for Centrifugo v5.
    """
    claims = {
        "sub": str(user_id), 
        "exp": int(time.time()) + ttl,
        "iat": int(time.time())
    }
    return jwt.encode(claims, settings.CENTRIFUGO_SECRET, algorithm="HS256")