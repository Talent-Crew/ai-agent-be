import json
import base64
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from google import genai
from google.genai import types
from django.conf import settings
from .models import InterviewSession, EvidenceSnippet
from channels.db import database_sync_to_async

class GeminiInterviewConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.session_data = await self.get_session(self.session_id)
        
        # Initialize Gemini Client
        self.client = genai.Client(
            api_key=settings.GEMINI_API_KEY, 
            http_options={'api_version': 'v1alpha'}
        )
        
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
            response_modalities=["AUDIO"]
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
        """Listens to Gemini, sends Audio to User, and Handles Tool Calls."""
        async for message in self.gemini_ws.receive():
            # 1. Handle Audio Response
            if message.server_content and message.server_content.model_turn:
                parts = message.server_content.model_turn.parts
                for part in parts:
                    if part.inline_data:
                        # Send raw audio bytes back to the candidate
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
        if self.gemini_task:
            self.gemini_task.cancel()