import logging
import asyncio
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from deepgram import DeepgramClient, DeepgramClientOptions, LiveTranscriptionEvents, LiveOptions
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
        
        # 🚀 1. OFFICIAL DEEPGRAM KEEPALIVE CONFIG
        config = DeepgramClientOptions(
            options={"keepalive": "true"}
        )
        
        # Initialize client with the KeepAlive config
        self.dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY, config)
        self.dg_connection = self.dg_client.listen.live.v("1")

        # The text buffer (Wait for "Done Speaking" button)
        self.transcript_buffer = ""

        def on_transcript(self_dg, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            
            # Only append finalized chunks that contain actual text
            if len(sentence) == 0 or not result.is_final:
                return
                
            self.transcript_buffer += sentence + " "
            logger.info(f"📝 Captured so far: {sentence}")

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        
        options = LiveOptions(
            model="nova-2", 
            language="en-US", 
            interim_results=True,
            smart_format=True,
            endpointing="100" # Low endpointing because we manually control the flow now
        )
        
        try:
            started = await asyncio.to_thread(self.dg_connection.start, options)
            if not started: raise Exception("Deepgram rejected connection")
            await self.accept()
            logger.info(f"✅ Deepgram Pipeline Active: {self.session_id}")
            
            # 🚀 2. THE MANUAL HEARTBEAT FAILSAFE
            # This resets Deepgram's 10-second death timer while Gemini is thinking
            async def keep_alive_pinger():
                while True:
                    await asyncio.sleep(3) # Ping every 3 seconds
                    try:
                        if hasattr(self, 'dg_connection'):
                            # Send explicit JSON heartbeat text-frame to Deepgram
                            await asyncio.to_thread(
                                self.dg_connection.send, 
                                json.dumps({"type": "KeepAlive"})
                            )
                    except Exception:
                        break # Stop pinging gracefully if the connection closes naturally

            # Start the heartbeat!
            asyncio.run_coroutine_threadsafe(keep_alive_pinger(), self.loop)
            
            # Start the actual interview flow
            asyncio.run_coroutine_threadsafe(
                self.start_interview_flow(),
                self.loop
            )
        except Exception as e:
            logger.error(f"❌ Deepgram Connection Failed: {e}")
            await self.close()

    async def start_interview_flow(self):
        try:
            intro_text = await self.brain.generate_intro()
            await self.speak_text(intro_text)
        except Exception as e:
            logger.error(f"❌ Intro Error: {e}")

    async def generate_response(self, text):
        try:
            ai_text = await self.brain.get_answer(text)
            await self.speak_text(ai_text)
        except Exception as e:
            logger.error(f"❌ Generation Error: {e}")

    async def speak_text(self, text):
        import base64
        await self.centrifugo.publish_text_message(self.session_id, text)
        await self.centrifugo.publish_event(self.session_id, "speech_start")
        
        options = SpeakOptions(model="aura-asteria-en", encoding="mp3")
        response = await asyncio.to_thread(
            self.dg_client.speak.v("1").stream, {"text": text}, options
        )
        
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
                # Keep streaming audio to Deepgram constantly
                await asyncio.to_thread(self.dg_connection.send, bytes_data)
            except Exception as e:
                logger.error(f"❌ Deepgram Relay Error: {e}")
        elif text_data:
            try:
                data = json.loads(text_data)
                
                # 🚀 3. THE MAGIC TRIGGER FROM THE FRONTEND
                if data.get("type") == "user_finished_speaking":
                    # Wait half a second just to let any final Deepgram text chunks arrive over the network
                    await asyncio.sleep(0.5) 
                    
                    final_text = getattr(self, 'transcript_buffer', "").strip()
                    
                    if final_text:
                        logger.info(f"🎤 USER CLICKED DONE. FULL PARAGRAPH: {final_text}")
                        self.transcript_buffer = "" # Clear buffer for the next question
                        await self.generate_response(final_text)
                    else:
                        logger.warning("⚠️ User clicked done, but they haven't spoken anything yet.")
                        
            except Exception as e:
                logger.error(f"❌ JSON Parse Error: {e}")

    async def disconnect(self, close_code):
        try:
            await asyncio.to_thread(self.dg_connection.finish)
        except Exception as e:
            logger.warning(f"⚠️ Deepgram disconnect error: {e}")
        await self.centrifugo.close()