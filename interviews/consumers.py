import logging
import asyncio
import json
import time # 🚀 1. WE NEED TIME FOR THE STOPWATCH
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
        
        config = DeepgramClientOptions(options={"keepalive": "true"})
        self.dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY, config)
        self.dg_connection = self.dg_client.listen.live.v("1")

        self.transcript_buffer = ""
        
        # 🚀 2. THE CHEATING STOPWATCH VARIABLES
        self.ai_finished_speaking_time = 0
        self.user_first_word_time = 0

        def on_transcript(self_dg, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) == 0 or not result.is_final:
                return
            
            # 🚀 3. RECORD THE EXACT MOMENT THEY START SPEAKING
            if self.user_first_word_time == 0:
                self.user_first_word_time = time.time()
                
            self.transcript_buffer += sentence + " "
            logger.info(f"📝 Captured so far: {sentence}")

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        
        options = LiveOptions(
            model="nova-2", 
            language="en-US", 
            interim_results=True,
            smart_format=True,
            endpointing="100" 
        )
        
        try:
            started = await asyncio.to_thread(self.dg_connection.start, options)
            if not started: raise Exception("Deepgram rejected connection")
            await self.accept()
            logger.info(f"✅ Deepgram Pipeline Active: {self.session_id}")
            
            async def keep_alive_pinger():
                while True:
                    await asyncio.sleep(3) 
                    try:
                        if hasattr(self, 'dg_connection'):
                            await asyncio.to_thread(
                                self.dg_connection.send, 
                                json.dumps({"type": "KeepAlive"})
                            )
                    except Exception:
                        break 

            asyncio.run_coroutine_threadsafe(keep_alive_pinger(), self.loop)
            asyncio.run_coroutine_threadsafe(self.start_interview_flow(), self.loop)
            
        except Exception as e:
            logger.error(f"❌ Deepgram Connection Failed: {e}")
            await self.close()

    async def start_interview_flow(self):
        try:
            intro_text = await self.brain.generate_intro()
            await self.speak_text(intro_text)
        except Exception as e:
            logger.error(f"❌ Intro Error: {e}")

    # 🚀 4. PASS THE PAUSE DURATION TO THE BRAIN
    async def generate_response(self, text, pause_duration):
        try:
            ai_text = await self.brain.get_answer(text, pause_duration)
            
            # Check if interview is complete
            if ai_text.startswith("FINISH_INTERVIEW:"):
                clean_text = ai_text.replace("FINISH_INTERVIEW:", "").strip()
                await self.speak_text(clean_text)
                
                # Tell Frontend to trigger the scorecard
                logger.info("🏁 Sending interview_complete event to frontend")
                await self.centrifugo.publish(
                    f"interviews:interview:{self.session_id}",
                    {"type": "interview_complete"}
                )
            else:
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
        
        # 🚀 5. START THE CLOCK WHEN AI FINISHES SPEAKING
        self.ai_finished_speaking_time = time.time()
        self.user_first_word_time = 0 # Reset for the next question

    async def receive(self, bytes_data=None, text_data=None):
        if bytes_data:
            try:
                await asyncio.to_thread(self.dg_connection.send, bytes_data)
            except Exception as e:
                logger.error(f"❌ Deepgram Relay Error: {e}")
        elif text_data:
            try:
                data = json.loads(text_data)
                
                if data.get("type") == "user_finished_speaking":
                    # We can remove the sleep here because the frontend now handles the delay!
                    final_text = getattr(self, 'transcript_buffer', "").strip()
                    
                    if final_text:
                        pause_duration = 0
                        if self.ai_finished_speaking_time > 0 and self.user_first_word_time > 0:
                            pause_duration = round(self.user_first_word_time - self.ai_finished_speaking_time, 2)
                            
                        logger.info(f"🎤 USER CLICKED DONE. GAP: {pause_duration}s | TEXT: {final_text}")
                        self.transcript_buffer = "" 
                        
                        # 🚀 THE SPEED BOOST: 
                        # We use create_task so we don't block the WebSocket from receiving new audio
                        asyncio.create_task(self.generate_response(final_text, pause_duration))
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