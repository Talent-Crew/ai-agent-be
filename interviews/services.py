from google import genai
from google.genai import types
from django.conf import settings
from .models import InterviewSession, EvidenceSnippet
import asyncio
import logging
import json

logger = logging.getLogger(__name__)

class InterviewerBrain:
    def __init__(self, session_id):
        self.session = InterviewSession.objects.select_related('job').get(id=session_id)
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_id = "gemini-2.5-flash"
        
        # 🚀 FIX 1: Initialize a persistent Chat Session for memory
        config = types.GenerateContentConfig(
            system_instruction=self.get_instructions(),
            tools=[self.get_tools()],
            temperature=0.7,
        )
        self.chat = self.client.chats.create(
            model=self.model_id,
            config=config
        )

    async def get_answer(self, text):
        logger.info(f"🧠 Gemini Thinking for: {text}")
        try:
            # 🚀 FIX 2: Send message to the chat session, not generate_content
            response = await asyncio.to_thread(
                self.chat.send_message,
                text
            )

            # 🚀 FIX 3: Check for function calls cleanly
            if response.function_calls:
                for tool_call in response.function_calls:
                    if tool_call.name == "record_evidence":
                        logger.info(f"📝 Logging Evidence: {tool_call.args}")
                        await self.save_evidence(tool_call.args)
                
                # 🚀 FIX 4: Send the tool execution result back to Gemini
                # This triggers Gemini to generate the actual spoken response!
                tool_result = types.Part.from_function_response(
                    name="record_evidence",
                    response={"status": "evidence_saved_successfully"}
                )
                
                response = await asyncio.to_thread(
                    self.chat.send_message,
                    tool_result
                )

            # Now we are guaranteed to have the text response
            if response.text:
                logger.info(f"🤖 Gemini Response: {response.text[:100]}...")
                return response.text
            
            return "Could you tell me more about that?"

        except Exception as e:
            logger.error(f"💥 Gemini Error: {e}", exc_info=True)
            return "I'm having a bit of trouble processing that. Can you repeat?"

    def get_instructions(self):
        job = self.session.job
        rubric_str = json.dumps(job.rubric_template)
        return (
            f"You are a world-class technical interviewer for the position of {job.title}. "
            f"Candidate Name: {self.session.candidate_name}. "
            f"Evaluation Rubric: {rubric_str}. "
            "Stay in character, be concise, and ask one follow-up question at a time. "
            "If the candidate demonstrates a skill in the rubric, use the record_evidence tool."
        )

    def get_tools(self):
        return types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="record_evidence",
                description="Log candidate proof for rubric items when they demonstrate a skill.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "metric": {"type": "STRING", "description": "The rubric metric being evaluated"},
                        "snippet": {"type": "STRING", "description": "The specific quote from the candidate"},
                        "score": {"type": "INTEGER", "description": "Confidence score from 1-10"}
                    },
                    "required": ["metric", "snippet", "score"]
                }
            )
        ])

    async def save_evidence(self, args):
        """Save evidence to database asynchronously."""
        try:
            await asyncio.to_thread(
                EvidenceSnippet.objects.create,
                session=self.session,
                metric_name=args.get('metric'),
                snippet=args.get('snippet'),
                confidence_score=args.get('score', 0)
            )
            logger.info(f"✅ Evidence saved: {args.get('metric')}")
        except Exception as e:
            logger.error(f"❌ Failed to save evidence: {e}", exc_info=True)