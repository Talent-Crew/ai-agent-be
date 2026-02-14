from google import genai
from google.genai import types
from django.conf import settings
from .models import InterviewSession
import asyncio
import logging
import json

logger = logging.getLogger(__name__)

class InterviewerBrain:
    def __init__(self, session_id):
        self.session = InterviewSession.objects.select_related('job').get(id=session_id)
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_id = "gemini-2.5-flash"
        
        # 🚀 STRIPPED TOOLS FOR MAXIMUM SPEED
        config = types.GenerateContentConfig(
            system_instruction=self.get_instructions(),
            temperature=0.7,
        )
        self.chat = self.client.chats.create(
            model=self.model_id,
            config=config
        )

    async def get_answer(self, text):
        logger.info(f"⚡ Fast Gemini thinking for: {text}")
        try:
            # Pure, direct text generation. No tools, no waiting.
            response = await asyncio.to_thread(
                self.chat.send_message,
                text
            )

            if response.text:
                logger.info(f"🤖 Gemini Response: {response.text[:100]}...")
                return response.text
            
            return "Could you tell me more about that?"

        except Exception as e:
            logger.error(f"💥 Gemini Error: {e}", exc_info=True)
            return "I missed that, can you repeat?"

    def get_instructions(self):
        job = self.session.job
        rubric_str = json.dumps(job.rubric_template)
        return (
            f"You are a fast-paced, conversational technical interviewer for the position of {job.title}. "
            f"Candidate Name: {self.session.candidate_name}. "
            f"Evaluation Rubric: {rubric_str}. "
            "Keep your responses very short, conversational, and ask exactly ONE follow-up question. Do not use markdown."
        )