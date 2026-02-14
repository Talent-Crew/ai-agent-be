import logging
import asyncio
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from deepgram.clients.speak.v1 import SpeakOptions
from django.conf import settings
from .services import InterviewerBrain
from .centrifugo_client import get_centrifugo_publisher

logger = logging.getLogger(__name__)

class UnifiedInterviewConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        # 🚀 CAPTURE THE RUNNING LOOP HERE
        self.loop = asyncio.get_running_loop()
        
        # Initialize Brain & Centrifugo
        self.brain = await asyncio.to_thread(InterviewerBrain, self.session_id)
        self.centrifugo = get_centrifugo_publisher()
        
        # Initialize Deepgram
        self.dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        self.dg_connection = self.dg_client.listen.live.v("1")

        # Define the event handler correctly
        def on_transcript(self_dg, result, **kwargs):
            transcript = result.channel.alternatives[0].transcript
            if result.is_final and len(transcript) > 0:
                logger.info(f"🎤 Confirmed Speech: {transcript}")
                # Use the captured loop to schedule the response
                asyncio.run_coroutine_threadsafe(
                    self.generate_response(transcript), 
                    self.loop
                )

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        
        # Fixed Options: Ensure integers and strict typing
        options = LiveOptions(
            model="nova-2",
            language="en-US",
            interim_results=True,
            utterance_end_ms='1000',  # Must be int
            vad_events=True,
            endpointing="300",
        )
        
        try:
            # Use the direct await since the SDK method is already async
            started = await asyncio.to_thread(self.dg_connection.start, options)
            if not started:
                raise Exception("Deepgram rejected connection")
            
            await self.accept()
            logger.info(f"✅ Deepgram Pipeline Active: {self.session_id}")
        except Exception as e:
            logger.error(f"❌ Deepgram Connection Failed: {e}")
            await self.close()

    async def generate_response(self, text):
        """Gemini reasoning -> Deepgram Aura TTS (Bulletproof MP3 Method)."""
        import base64
        try:
            ai_text = await self.brain.get_answer(text)
            await self.centrifugo.publish_text_message(self.session_id, ai_text)
            
            # 🚀 1. Switch to standard MP3 encoding
            options = SpeakOptions(
                model="aura-asteria-en",
                encoding="mp3", 
            )
            
            await self.centrifugo.publish_event(self.session_id, "speech_start")
            
            response = await asyncio.to_thread(
                self.dg_client.speak.v("1").stream, {"text": ai_text}, options
            )
            
            def process_full_audio():
                # 🚀 2. Gather all chunks into ONE complete MP3 file
                audio_bytes = b""
                for chunk in response.stream:
                    if chunk:
                        audio_bytes += chunk
                
                # 🚀 3. Encode the entire MP3 as a single Base64 string
                b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
                
                # Publish the complete file to Centrifugo
                asyncio.run_coroutine_threadsafe(
                    self.centrifugo.publish(
                        f"interviews:interview:{self.session_id}",
                        {"type": "tts_audio_complete", "audio": b64_audio}
                    ),
                    self.loop
                )

            # Run in thread so we don't block the websocket
            await asyncio.to_thread(process_full_audio)
            await self.centrifugo.publish_event(self.session_id, "speech_end")
            
        except Exception as e:
            logger.error(f"❌ Generation Error: {e}")

    async def receive(self, bytes_data=None, text_data=None):
        if bytes_data:
            # Relay binary audio to Deepgram (non-blocking send)
            try:
                await asyncio.to_thread(self.dg_connection.send, bytes_data)
            except Exception as e:
                logger.error(f"❌ Deepgram Relay Error: {e}")
        
        elif text_data:
            try:
                data = json.loads(text_data)
                # This allows us to test the Gemini -> TTS -> Centrifugo pipe 
                # even if the microphone/VAD fails.
                if data.get("type") == "force_test":
                    logger.info("🚀 Force-test triggered. Bypassing VAD.")
                    await self.generate_response("Hello! This is a forced test response.")
            except Exception as e:
                logger.error(f"❌ JSON Parse Error: {e}")

    async def disconnect(self, close_code):
        try:
            await asyncio.to_thread(self.dg_connection.finish)
        except Exception as e:
            logger.warning(f"⚠️ Deepgram disconnect error: {e}")
        await self.centrifugo.close()