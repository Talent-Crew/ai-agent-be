import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from .services import InterviewerBrain

class GeminiLiveConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.brain = InterviewerBrain(self.session_id)
        
        # Connect to Gemini 3 Multimodal Live API
        self.gemini_session = await self.brain.client.aio.live.connect(
            model=self.brain.model_id,
            config=types.LiveConnectConfig(
                system_instruction=self.brain.get_system_instruction(),
                tools=self.brain.get_tools(),
                response_modalities=["AUDIO"] # Gemini replies with voice!
            )
        )
        await self.accept()

    async def receive(self, bytes_data=None, text_data=None):
        """
        Receives raw PCM bytes from Centrifugo/React 
        and pipes them to Gemini 3.
        """
        if bytes_data:
            # Send audio chunks to Gemini
            await self.gemini_session.send(input=bytes_data, end_of_turn=False)
        
        # Listen for Gemini's response (Audio + Tool Calls)
        async for message in self.gemini_session.receive():
            if message.server_content and message.server_content.model_turn:
                # Send Gemini's voice back to the candidate
                audio_bytes = message.server_content.model_turn.parts[0].inline_data.data
                await self.send(bytes_data=audio_bytes)
            
            if message.tool_call:
                # Handle the record_evidence tool
                for fc in message.tool_call.function_calls:
                    result = self.brain.handle_tool_call(fc)
                    await self.gemini_session.send(
                        tool_response=types.LiveClientToolResponse(
                            function_responses=[types.FunctionResponse(name=fc.name, response=result)]
                        )
                    )