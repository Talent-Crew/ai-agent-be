from google import genai
from google.genai import types
from django.conf import settings
from .models import InterviewSession, EvidenceSnippet
import asyncio
import logging

logger = logging.getLogger(__name__)

class InterviewerBrain:
    def __init__(self, session_id):
        self.session = InterviewSession.objects.select_related('job').get(id=session_id)
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_id = "gemini-2.0-flash"

    async def get_answer(self, text):
        """Standard text generation with tool support."""
        logger.info(f"🧠 Asking Gemini about: {text}")
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_id,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=self.get_instructions(),
                    tools=[self.get_tools()]
                )
            )
            logger.info(f"🤖 Gemini responded successfully.")
            # Check for tool calls (Evidence Logging)
            if response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        await self.save_evidence(part.function_call.args)

            return response.text
        except Exception as e:
            logger.error(f"💥 Gemini API Crash: {e}")
            return "I'm having trouble thinking right now."

    def get_instructions(self):
        job = self.session.job
        return f"Interviewer for {job.title}. Rubric: {job.rubric_template}. Be concise."

    def get_tools(self):
        return types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="record_evidence",
                description="Log candidate proof for rubric items.",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "metric": {"type": "STRING"},
                        "snippet": {"type": "STRING"},
                        "score": {"type": "INTEGER"}
                    }
                }
            )
        ])

    @asyncio.to_thread
    def save_evidence(self, args):
        EvidenceSnippet.objects.create(
            session=self.session,
            metric_name=args.get('metric'),
            snippet=args.get('snippet'),
            confidence_score=args.get('score', 0)
        )