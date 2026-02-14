import json
import base64
import asyncio
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from google import genai
from google.genai import types
from django.conf import settings
from .models import InterviewSession, EvidenceSnippet
from channels.db import database_sync_to_async
from .tts_service import get_tts_service
from .centrifugo_client import get_centrifugo_publisher

logger = logging.getLogger(__name__)

class GeminiInterviewConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.session_data = await self.get_session(self.session_id)
        
        # Initialize Gemini Client
        self.client = genai.Client(
            api_key=settings.GEMINI_API_KEY, 
            http_options={'api_version': 'v1alpha'}
        )
        
        # Initialize Kokoro TTS Service
        logger.info(f"🎤 Initializing TTS for session {self.session_id}")
        self.tts_service = get_tts_service()
        
        # Initialize Centrifugo Publisher
        self.centrifugo = get_centrifugo_publisher()
        
        # Connect to Gemini Multimodal Live API
        # We use a Task to handle the background receive loop
        self.gemini_task = None
        await self.accept()
        
        # Start Gemini Session
        await self.start_gemini_session()

    async def start_gemini_session(self):
        config = types.LiveConnectConfig(
            model="models/gemini-2.0-flash-exp", # Gemini 3 Preview / 2.0 Flash
            system_instruction=self.get_instructions(),
            tools=[{
                "function_declarations": [{
                    "name": "record_evidence",
                    "description": "Log technical proof from the candidate's speech.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "metric": {"type": "STRING", "description": "Rubric item name"},
                            "snippet": {"type": "STRING", "description": "Candidate's exact words"},
                            "score": {"type": "INTEGER", "description": "1-10 rating"}
                        },
                        "required": ["metric", "snippet", "score"]
                    }
                }]
            }],
            response_modalities=["TEXT"]  # Changed from AUDIO - using Kokoro for TTS
        )

        # Connect to Google's WebSocket
        async with self.client.aio.live.connect(model=config.model, config=config) as gemini_ws:
            self.gemini_ws = gemini_ws
            # Spawn a task to listen for Gemini's responses
            self.gemini_task = asyncio.create_task(self.receive_from_gemini())
            
            # Keep the connection alive
            while True:
                await asyncio.sleep(1)

    async def receive(self, bytes_data=None, text_data=None):
        """Receives audio from Frontend (Centrifugo/WebSocket) and sends to Gemini."""
        if bytes_data:
            # bytes_data is the raw PCM 16bit 16kHz audio
            await self.gemini_ws.send(input=bytes_data, end_of_turn=False)

    async def receive_from_gemini(self):
        """Listens to Gemini, processes TEXT responses with Kokoro TTS, and Handles Tool Calls."""
        sequence_number = 0
        
        async for message in self.gemini_ws.receive():
            # 1. Handle TEXT Response (NEW: process with Kokoro TTS)
            if message.server_content and message.server_content.model_turn:
                parts = message.server_content.model_turn.parts
                for part in parts:
                    # Extract text from Gemini response
                    if hasattr(part, 'text') and part.text:
                        text_response = part.text
                        logger.info(f"💬 Gemini says: {text_response[:100]}...")
                        
                        # Send text message to frontend (optional, for display)
                        await self.centrifugo.publish_text_message(
                            self.session_id, 
                            text_response,
                            message_type="interviewer"
                        )
                        
                        # Generate and stream audio via Kokoro TTS
                        try:
                            logger.info("🎵 Starting Kokoro TTS generation...")
                            await self.centrifugo.publish_event(
                                self.session_id,
                                "speech_start"
                            )
                            
                            # Stream audio chunks to Centrifugo
                            async for audio_chunk in self.tts_service.text_to_audio_stream(text_response):
                                success = await self.centrifugo.publish_audio_chunk(
                                    self.session_id,
                                    audio_chunk,
                                    sequence=sequence_number
                                )
                                if success:
                                    sequence_number += 1
                                else:
                                    logger.warning("Failed to publish audio chunk")
                            
                            await self.centrifugo.publish_event(
                                self.session_id,
                                "speech_end"
                            )
                            logger.info("✅ Kokoro TTS streaming complete")
                            
                        except Exception as e:
                            logger.error(f"❌ TTS streaming error: {e}")
                    
                    # Legacy: Handle inline_data (in case Gemini sends audio)
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        logger.warning("Received audio from Gemini (unexpected)")
                        # Could still forward it as fallback
                        await self.send(bytes_data=part.inline_data.data)

            # 2. Handle Evidence Extraction (Tool Call)
            if message.tool_call:
                for fc in message.tool_call.function_calls:
                    await self.save_evidence(fc.args)
                    # Respond to Gemini that tool was successful
                    await self.gemini_ws.send(
                        tool_response=types.LiveClientToolResponse(
                            function_responses=[types.FunctionResponse(
                                name=fc.name,
                                id=fc.id,
                                response={"result": "Evidence logged successfully"}
                            )]
                        )
                    )

    @database_sync_to_async
    def get_session(self, session_id):
        return InterviewSession.objects.select_related('job').get(id=session_id)

    @database_sync_to_async
    def save_evidence(self, args):
        EvidenceSnippet.objects.create(
            session_id=self.session_id,
            metric_name=args['metric'],
            snippet=args['snippet'],
            confidence_score=args['score']
        )

    def get_instructions(self):
        job = self.session_data.job
        return f"You are an interviewer for {job.title}. Use this rubric: {job.rubric_template}. Speak naturally."

    async def disconnect(self, close_code):
        """Cleanup resources on disconnect."""
        if self.gemini_task:
            self.gemini_task.cancel()
        
        # Close Centrifugo publisher session
        if hasattr(self, 'centrifugo'):
            await self.centrifugo.close()
        
        logger.info(f"🔌 Session {self.session_id} disconnected")