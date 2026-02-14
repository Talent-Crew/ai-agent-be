"""
Centrifugo HTTP API Client for Publishing Audio Streams
Handles real-time audio chunk publishing to React frontend
"""


import aiohttp
import base64
import logging
from typing import Optional, Dict, Any
from django.conf import settings

logger = logging.getLogger(__name__)


class CentrifugoPublisher:
    """
    Async HTTP client for publishing messages to Centrifugo channels.
    Used for streaming TTS audio chunks to frontend clients.
    """
    
    def __init__(self):
        """Initialize Centrifugo publisher with API credentials."""
        self.api_url = f"{settings.CENTRIFUGO_HOST}/api"
        self.api_key = settings.CENTRIFUGO_API_KEY
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"apikey {self.api_key}"
                }
            )
        return self.session
    
    async def publish(
        self, 
        channel: str, 
        data: Any,
        is_binary: bool = False
    ) -> Dict[str, Any]:
        """
        Publish data to a Centrifugo channel.
        
        Args:
            channel: Channel name (e.g., "interview:session-id")
            data: Data to publish (dict for JSON, bytes for binary)
            is_binary: If True, base64-encode binary data
        
        Returns:
            API response dict
        """
        try:
            session = await self._get_session()
            
            # Prepare payload
            payload = {
                "method": "publish",
                "params": {
                    "channel": channel
                }
            }
            
            # Handle binary data (audio chunks)
            if is_binary and isinstance(data, bytes):
                # Base64 encode for JSON transport
                payload["params"]["data"] = {
                    "audio": base64.b64encode(data).decode('utf-8'),
                    "type": "audio_chunk"
                }
            else:
                payload["params"]["data"] = data
            
            # Send HTTP POST to Centrifugo API
            async with session.post(self.api_url, json=payload) as response:
                result = await response.json()
                
                if response.status != 200:
                    logger.error(f"Centrifugo publish failed: {result}")
                    return {"error": result}
                
                return result
                
        except Exception as e:
            logger.error(f"Failed to publish to Centrifugo: {e}")
            return {"error": str(e)}
    
    async def publish_audio_chunk(
        self, 
        session_id: str, 
        audio_chunk: bytes,
        sequence: Optional[int] = None
    ) -> bool:
        """
        Publish audio chunk to interview channel.
        
        Args:
            session_id: Interview session UUID
            audio_chunk: PCM 16-bit audio bytes
            sequence: Optional sequence number for ordering
        
        Returns:
            True if successful, False otherwise
        """
        channel = f"interviews:interview:{session_id}"
        
        payload = {
            "audio": base64.b64encode(audio_chunk).decode('utf-8'),
            "type": "tts_audio",
            "format": "pcm16",
            "sample_rate": 16000,
            "channels": 1
        }
        
        if sequence is not None:
            payload["sequence"] = sequence
        
        result = await self.publish(channel, payload, is_binary=False)
        
        success = "error" not in result
        if not success:
            logger.warning(f"Audio chunk publish failed: {result.get('error')}")
        
        return success
    
    async def publish_text_message(
        self, 
        session_id: str, 
        message: str,
        message_type: str = "interviewer"
    ) -> bool:
        """
        Publish text message to interview channel.
        
        Args:
            session_id: Interview session UUID
            message: Text message
            message_type: Type of message (interviewer, system, etc.)
        
        Returns:
            True if successful
        """
        channel = f"interviews:interview:{session_id}"
        
        payload = {
            "type": "text_message",
            "message": message,
            "sender": message_type
        }
        
        result = await self.publish(channel, payload)
        return "error" not in result
    
    async def publish_event(
        self,
        session_id: str,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Publish system event to interview channel.
        
        Args:
            session_id: Interview session UUID
            event_type: Event type (e.g., "speech_start", "speech_end")
            event_data: Optional event metadata
        
        Returns:
            True if successful
        """
        channel = f"interviews:interview:{session_id}"
        
        payload = {
            "type": "event",
            "event": event_type,
            "data": event_data or {}
        }
        
        result = await self.publish(channel, payload)
        return "error" not in result
    
    async def close(self):
        """Close aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("🔌 Centrifugo publisher session closed")


# Convenience function for getting publisher instance
def get_centrifugo_publisher() -> CentrifugoPublisher:
    """Get a new Centrifugo publisher instance."""
    return CentrifugoPublisher()
