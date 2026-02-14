from google import genai
from google.genai import types
from django.conf import settings
from .models import InterviewSession, PerAnswerMetric, EvidenceSnippet
import asyncio
import logging
import json

logger = logging.getLogger(__name__)

class InterviewerBrain:
    def __init__(self, session_id):
        self.session = InterviewSession.objects.select_related('job').get(id=session_id)
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.model_id = "gemini-2.5-flash"
        
        # 🚀 1. LOAD THE DYNAMIC RUBRIC
        rubric = self.session.job.rubric_template
        self.metrics_list = rubric.get('metrics', [])
        self.current_metric_index = 0
        
        self.current_difficulty = 3 
        self.last_question_asked = None

        config = types.GenerateContentConfig(
            system_instruction=self.get_instructions(),
            temperature=0.7,
        )
        self.chat = self.client.chats.create(model=self.model_id, config=config)

    def get_instructions(self):
        job = self.session.job
        rubric = job.rubric_template
        
        # Safely extract the fixed fields from the JSON
        language = rubric.get('primary_language', 'General Programming')
        level = rubric.get('experience_level', 'Mid-Level')
        skills = ", ".join(rubric.get('core_skills', []))
        focus = ", ".join(rubric.get('evaluation_focus', ['Understanding', 'Communication']))
        
        return (
            f"You are a dynamic technical interviewer hiring a {level} {job.title}. "
            f"Candidate: {self.session.candidate_name}. "
            f"Primary Language: {language}. "
            f"Core Skills to cover: {skills}. "
            f"Evaluation Focus: {focus}. "
            "INSTRUCTIONS: "
            "1. Do not interrogate. Have a natural, flowing conversation. "
            "2. If they don't know a specific skill, pivot smoothly to the next skill in the list. "
            "3. Ask exactly ONE question at a time. Keep it conversational and under 2 sentences."
        )

    async def generate_intro(self):
        logger.info("🎬 Generating Interview Intro")
        job_title = self.session.job.title
        candidate = self.session.candidate_name
        
        prompt = (
            f"SYSTEM COMMAND: The interview has just started. Greet {candidate}. "
            f"Introduce yourself as the TalentCrew AI Interviewer for the {job_title} role. "
            "End by asking if they are ready to begin. Keep it natural and under 3 sentences."
        )
        response = await asyncio.to_thread(self.chat.send_message, prompt)
        
        self.session.current_stage = 'technical'
        await asyncio.to_thread(self.session.save)
        
        return response.text

    # --- TRACK 1: THE FAST TALKER ---
    async def get_answer(self, user_text):
        try:
            if self.current_metric_index >= len(self.metrics_list):
                return "We've covered everything I needed to ask. Do you have any questions for me before we wrap up?"

            current_metric_data = self.metrics_list[self.current_metric_index]
            metric_name = current_metric_data.get('name')
            metric_criteria = current_metric_data.get('criteria')
            passing_threshold = current_metric_data.get('threshold', 6)

            if self.last_question_asked:
                # 🚀 2. FAST GRADING
                eval_data = await self._grade_answer(self.last_question_asked, user_text, metric_name)
                score = eval_data.get('confidence_score', 0)
                
                # 🚀 3. FIRE THE BACKGROUND JUDGE (Stretch Goals!)
                # This runs concurrently and saves to Postgres without delaying the audio
                asyncio.create_task(
                    self._save_background_metrics(self.last_question_asked, user_text, eval_data, metric_name, score)
                )

                # 🚀 4. PYTHON LOGIC FOR DIFFICULTY & RUBRIC TRANSITION
                if score >= passing_threshold:
                    logger.info(f"✅ Passed {metric_name} (Score: {score}). Moving to next metric.")
                    self.current_metric_index += 1
                    self.current_difficulty = 3 
                    
                    if self.current_metric_index >= len(self.metrics_list):
                        directive = "The candidate passed the final topic. Tell them the technical portion is complete and smoothly wrap up the interview."
                    else:
                        next_metric = self.metrics_list[self.current_metric_index]['name']
                        next_criteria = self.metrics_list[self.current_metric_index]['criteria']
                        directive = f"The candidate did great. Transition to the next topic: {next_metric}. Focus on: {next_criteria}. Difficulty: Level 3."
                else:
                    logger.info(f"❌ Struggled with {metric_name} (Score: {score}). Retrying.")
                    self.current_difficulty = max(1, self.current_difficulty - 1)
                    directive = (
                        f"The candidate struggled with {metric_name}. "
                        f"Lower the difficulty to Level {self.current_difficulty} and ask an easier question regarding: {metric_criteria}."
                    )
            else:
                directive = f"Start the technical interview. Ask a Level 3 question about the first topic: {metric_name} ({metric_criteria})."

            ai_spoken_response = await self._generate_next_question(directive, user_text)
            self.last_question_asked = ai_spoken_response
            
            return ai_spoken_response

        except Exception as e:
            logger.error(f"💥 Brain Pipeline Error: {e}", exc_info=True)
            return "Could you elaborate on that?"

    async def _grade_answer(self, question, answer, metric_name):
        """Strictly returns JSON scoring data using Gemini's massive speed."""
        prompt = (
            f"Analyze this interaction for the metric '{metric_name}'.\n"
            f"Question: {question}\nCandidate Answer: {answer}\n"
            "Grade the technical accuracy, extract the exact quote as evidence, and check for cheating or bias."
        )
        
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "confidence_score": {"type": "INTEGER", "description": "1 to 10"},
                    "evidence_extracted": {"type": "STRING", "description": "Exact quote from candidate"},
                    "is_cheating": {"type": "BOOLEAN", "description": "True if it sounds copy-pasted or robotic"},
                    "cheating_reason": {"type": "STRING"},
                    "bias_flag": {"type": "BOOLEAN", "description": "True if the question was unfair"}
                }
            }
        )
        
        # We use a separate direct API call to keep the main chat history clean
        response = await asyncio.to_thread(
            self.client.models.generate_content, model=self.model_id, contents=prompt, config=config
        )
        return json.loads(response.text)

    # --- TRACK 2: THE BACKGROUND JUDGE ---
    async def _save_background_metrics(self, question, answer, eval_data, metric_name, score):
        """Runs silently in the background. Does NOT block the voice audio."""
        try:
            # 1. Save the Per-Answer deep analysis (Stretch Goals)
            await asyncio.to_thread(
                PerAnswerMetric.objects.create,
                session=self.session,
                question_asked=question,
                candidate_answer=answer,
                confidence_score=score,
                evidence_extracted=eval_data.get('evidence_extracted', ''),
                is_cheating_suspected=eval_data.get('is_cheating', False),
                cheating_reason=eval_data.get('cheating_reason', ''),
                bias_flag=eval_data.get('bias_flag', False)
            )
            
            # 2. If they passed, save it to the Evidence Tracker for the final scorecard!
            rubric = self.session.job.rubric_template
            passing_threshold = next((m.get('threshold', 6) for m in rubric.get('metrics', []) if m.get('name') == metric_name), 6)
            
            if score >= passing_threshold:
                await asyncio.to_thread(
                    EvidenceSnippet.objects.create,
                    session=self.session,
                    metric_name=metric_name,
                    snippet=eval_data.get('evidence_extracted', ''),
                    confidence_score=score
                )
                
            logger.info("✅ Background metrics & evidence saved to DB!")
        except Exception as e:
            logger.error(f"❌ Background Save Failed: {e}")

    async def _generate_next_question(self, directive, user_text):
        """Generates the conversational text based on Python's strict directive."""
        prompt = (
            f"Candidate just said: '{user_text}'.\n"
            f"SYSTEM DIRECTIVE: {directive}\n"
        )
        response = await asyncio.to_thread(
            self.client.models.generate_content, model=self.model_id, contents=prompt
        )
        return response.text