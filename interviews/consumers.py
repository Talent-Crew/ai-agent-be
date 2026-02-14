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
                # Use the consumer's loop to schedule the response
                asyncio.run_coroutine_threadsafe(
                    self.generate_response(transcript), 
                    asyncio.get_event_loop()
                )

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        
        # Fixed Options: Ensure integers and strict typing
        options = LiveOptions(
            model="nova-2",
            language="en-US",
            encoding="linear16",
            sample_rate=16000,
            channels=1,
            interim_results=True,
            utterance_end_ms=1000,  # Must be int
            vad_events=True,
            endpointing=300         # Must be int
        )
        
        try:
            # The .start() method is synchronous in some SDK versions, 
            # but usually returns True/False or raises on 400.
            if await asyncio.to_thread(self.dg_connection.start, options) is False:
                raise Exception("Deepgram rejected connection")
                
            await self.accept()
            logger.info(f"✅ Deepgram Pipeline Active: {self.session_id}")
        except Exception as e:
            logger.error(f"❌ Deepgram Connection Failed: {e}")
            await self.close()

    async def generate_response(self, text):
        """Gemini reasoning -> Deepgram Aura TTS."""
        try:
            ai_text = await self.brain.get_answer(text)
            await self.centrifugo.publish_text_message(self.session_id, ai_text)
            
            options = SpeakOptions(
                model="aura-asteria-en",
                encoding="linear16",
                sample_rate=16000,
            )
            
            await self.centrifugo.publish_event(self.session_id, "speech_start")
            
            # Use the newer SDK pattern for streaming TTS
            response = await asyncio.to_thread(
                self.dg_client.speak.v("1").stream, {"text": ai_text}, options
            )
            
            # response.stream is a block-generator, iterate carefully
            seq = 0
            for chunk in response.stream:
                if chunk:
                    await self.centrifugo.publish_audio_chunk(self.session_id, chunk, sequence=seq)
                    seq += 1
                await asyncio.sleep(0.01) # Small sleep to yield
                
            await self.centrifugo.publish_event(self.session_id, "speech_end")
            
        except Exception as e:
            logger.error(f"❌ Generation Error: {e}")

    async def receive(self, bytes_data=None, text_data=None):
        if bytes_data:
            # Deepgram SDK handle: send() is typically thread-safe but 
            # ensure dg_connection is actually started.
            try:
                self.dg_connection.send(bytes_data)
            except Exception as e:
                logger.error(f"❌ Relay Error: {e}")

    async def disconnect(self, close_code):
        try:
            self.dg_connection.finish()
        except:
            pass
        await self.centrifugo.close()