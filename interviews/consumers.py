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
        self.loop = asyncio.get_running_loop()
        self.brain = await asyncio.to_thread(InterviewerBrain, self.session_id)
        self.centrifugo = get_centrifugo_publisher()
        self.dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        self.dg_connection = self.dg_client.listen.live.v("1")

        def on_transcript(self_dg, result, **kwargs):
            transcript = result.channel.alternatives[0].transcript
            if result.is_final and len(transcript) > 0:
                logger.info(f"🎤 Confirmed Speech: {transcript}")
                asyncio.run_coroutine_threadsafe(
                    self.generate_response(transcript), 
                    self.loop
                )

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        
        options = LiveOptions(
            model="nova-2", language="en-US", interim_results=True,
            utterance_end_ms="1000", vad_events=True, endpointing="1500" 
        )
        
        try:
            started = await asyncio.to_thread(self.dg_connection.start, options)
            if not started: raise Exception("Deepgram rejected connection")
            await self.accept()
            logger.info(f"✅ Deepgram Pipeline Active: {self.session_id}")
            
            # 🚀 PHASE 2: TRIGGER PROACTIVE INTRO ON CONNECT
            asyncio.run_coroutine_threadsafe(
                self.start_interview_flow(),
                self.loop
            )
        except Exception as e:
            logger.error(f"❌ Deepgram Connection Failed: {e}")
            await self.close()

    async def start_interview_flow(self):
        """Kicks off the interview as soon as the socket connects."""
        try:
            intro_text = await self.brain.generate_intro()
            await self.speak_text(intro_text)
        except Exception as e:
            logger.error(f"❌ Intro Error: {e}")

    async def generate_response(self, text):
        """Standard conversational turn."""
        try:
            ai_text = await self.brain.get_answer(text)
            await self.speak_text(ai_text)
        except Exception as e:
            logger.error(f"❌ Generation Error: {e}")

    async def speak_text(self, text):
        """Reusable Deepgram MP3 TTS logic."""
        import base64
        
        # Publish text to the frontend UI
        await self.centrifugo.publish_text_message(self.session_id, text)
        await self.centrifugo.publish_event(self.session_id, "speech_start")
        
        # Generate the MP3
        options = SpeakOptions(model="aura-asteria-en", encoding="mp3")
        response = await asyncio.to_thread(
            self.dg_client.speak.v("1").stream, {"text": text}, options
        )
        
        # Gather the file and send it
        def process_full_audio():
            audio_bytes = b""
            for chunk in response.stream:
                if chunk: audio_bytes += chunk
            
            b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
            asyncio.run_coroutine_threadsafe(
                self.centrifugo.publish(
                    f"interviews:interview:{self.session_id}",
                    {"type": "tts_audio_complete", "audio": b64_audio}
                ),
                self.loop
            )

        await asyncio.to_thread(process_full_audio)
        await self.centrifugo.publish_event(self.session_id, "speech_end")

    async def receive(self, bytes_data=None, text_data=None):
        if bytes_data:
            try:
                await asyncio.to_thread(self.dg_connection.send, bytes_data)
            except Exception as e:
                logger.error(f"❌ Deepgram Relay Error: {e}")
        
        elif text_data:
            try:
                data = json.loads(text_data)
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