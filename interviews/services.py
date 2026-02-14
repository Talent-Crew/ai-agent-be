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
        
        rubric = self.session.job.rubric_template
        self.languages = rubric.get('languages', ['General Programming'])
        self.level = rubric.get('experience_level', 'Mid-Level')
        self.core_skills = rubric.get('core_skills', ['Core Concepts'])
        self.focus = rubric.get('evaluation_focus', ['Understanding'])
        
        self.turn_count = 0
        self.max_turns = 6 
        self.last_question_asked = None
        self.current_topic_drill_depth = 0

        config = types.GenerateContentConfig(
            system_instruction=self.get_instructions(),
            temperature=0.7,
        )
        self.chat = self.client.chats.create(model=self.model_id, config=config)

    def get_instructions(self):
        skills_str = ", ".join(self.core_skills)
        focus_str = ", ".join(self.focus)
        languages_str = ", ".join(self.languages)
        return (
            f"You are a dynamic technical interviewer hiring a {self.level} {self.session.job.title}. "
            f"Candidate: {self.session.candidate_name}. "
            f"Languages/Technologies to test: {languages_str}. "
            f"Core Skills to cover: {skills_str}. "
            f"Evaluation Focus: {focus_str}. "
            "INSTRUCTIONS: "
            "1. Do not interrogate. Have a natural, flowing conversation. "
            "2. Ask questions that cover ALL the languages/technologies listed. Mix language-specific and cross-language questions naturally. "
            "3. If they don't know a specific skill or language, pivot smoothly to the next skill or language in the list. "
            "4. Ask exactly ONE question at a time. Keep it conversational and under 2 sentences."
        )

    async def generate_intro(self):
        logger.info("🎬 Generating Interview Intro")
        languages_str = ", ".join(self.languages)
        prompt = (
            f"SYSTEM COMMAND: The interview has just started. Greet {self.session.candidate_name}. "
            f"Introduce yourself as the AI Interviewer for the {self.session.job.title} role. "
            f"Briefly mention we'll be discussing {languages_str} and related technical skills. "
            "End by asking if they are ready to begin. Keep it natural and under 3 short sentences."
        )
        response = await asyncio.to_thread(self.chat.send_message, prompt)
        
        self.session.current_stage = 'technical'
        await asyncio.to_thread(self.session.save)
        return response.text

    def _get_history_context(self):
        metrics = list(PerAnswerMetric.objects.filter(session=self.session).order_by('-timestamp')[:3])
        metrics.reverse()
        
        context = ""
        for i, metric in enumerate(metrics):
            context += f"Previous Question: {metric.question_asked}\n"
            context += f"Candidate Answered: {metric.candidate_answer}\n"
            context += f"Score: {metric.confidence_score}/10\n\n"
        return context

    async def get_answer(self, user_text, pause_duration=0):
        try:
            # Increment turn count first
            self.turn_count += 1

            # Check if interview should end
            if self.turn_count >= self.max_turns:
                logger.info(f"🏁 INTERVIEW COMPLETE | Total Turns: {self.turn_count}")
                return "FINISH_INTERVIEW: It's been great chatting with you! We've covered a wide range of topics. I'll pass my notes over to the team, and they'll be in touch. Do you have any final questions?"

            # Get conversation history
            history_context = await asyncio.to_thread(self._get_history_context)
            
            # 🚀 SINGLE-PASS BRAIN: LLM decides everything in ONE call
            skills_str = ", ".join(self.core_skills)
            languages_str = ", ".join(self.languages)
            
            prompt = (
                f"Candidate: {self.session.candidate_name}\n"
                f"Languages/Technologies: {languages_str}\n"
                f"Core Skills to Cover: {skills_str}\n"
                f"Current Topic Drill Depth: {self.current_topic_drill_depth}\n"
                f"Time taken before candidate started speaking: {pause_duration}s\n\n"
                f"--- PREVIOUS CONVERSATION HISTORY ---\n{history_context}\n"
                f"--- CURRENT EXCHANGE ---\n"
                f"Last Question: {self.last_question_asked or 'This is the first question'}\n"
                f"Candidate Answer: {user_text}\n\n"
                "YOUR TASK: Evaluate the answer AND generate the next question in ONE RESPONSE.\n\n"
                "STEP 1: GRADE THE ANSWER (1-10 for understanding, 1-10 for explainability)\n"
                "- Score 8-10 (EXCELLENT): Specific architectural decisions, real-world tools, clear problem-solving.\n"
                "- Score 5-7 (AVERAGE): Technically correct but shallow.\n"
                "- Score 1-4 (POOR): Incorrect, dodges question, or zero technical knowledge.\n"
                "- is_off_topic: TRUE if answer is nonsense or completely unrelated.\n"
                "- is_cheating: TRUE if pause_duration > 8s AND answer sounds robotic/textbook, OR if massive unnatural spike in fluency compared to history.\n"
                "- needs_clarification: TRUE ONLY if they explicitly ask you to repeat/clarify.\n\n"
                "STEP 2: DECIDE NEXT QUESTION BASED ON SCORE\n"
                "- If needs_clarification: Rephrase the previous question simply. Set did_pivot=false.\n"
                "- If is_cheating: Call them out gently. Ask for explanation in their own words. Set did_pivot=false.\n"
                "- If is_off_topic: Be politely stern, ask them to stay focused. Pivot to DIFFERENT skill. Set did_pivot=true.\n"
                "- If Score < 4: Say 'No worries!' and PIVOT to a COMPLETELY DIFFERENT skill. Set did_pivot=true.\n"
                "- If Score >= 8 AND drill_depth < 2: Ask specific follow-up to go deeper (drill down). Set did_pivot=false.\n"
                "- If Score >= 8 AND drill_depth >= 2: Acknowledge briefly, pivot to DIFFERENT skill. Set did_pivot=true.\n"
                "- If Score 5-7: Acknowledge answer, move to next skill. Set did_pivot=true.\n\n"
                "STEP 3: FORMAT YOUR RESPONSE\n"
                "- next_question: Maximum 2 sentences. Sound casual and human. End with ONE clear question.\n"
                "- Extract exact quote as evidence_extracted.\n"
                "- Explain what was missing in critique.\n"
                "- Provide ideal_answer (10/10 response example).\n"
                "- List specific technical_concepts_missed (e.g., 'Indexing', 'N+1 queries').\n\n"
                "Return comprehensive JSON with ALL fields."
            )

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "understanding_score": {"type": "INTEGER"},
                        "explainability_score": {"type": "INTEGER"},
                        "is_cheating": {"type": "BOOLEAN"},
                        "is_off_topic": {"type": "BOOLEAN"},
                        "needs_clarification": {"type": "BOOLEAN"},
                        "did_pivot": {"type": "BOOLEAN"},
                        "next_question": {"type": "STRING"},
                        "evidence_extracted": {"type": "STRING"},
                        "critique": {"type": "STRING"},
                        "ideal_answer": {"type": "STRING"},
                        "technical_concepts_missed": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"}
                        },
                        "bias_flag": {"type": "BOOLEAN"}
                    }
                }
            )

            # 🚀 ONE CALL TO GEMINI
            response = await asyncio.to_thread(
                self.client.models.generate_content, 
                model=self.model_id, 
                contents=prompt, 
                config=config
            )
            data = json.loads(response.text)

            # Extract results
            score = data.get('understanding_score', 0)
            explainability = data.get('explainability_score', 0)
            is_cheating = data.get('is_cheating', False)
            is_off_topic = data.get('is_off_topic', False)
            needs_clarification = data.get('needs_clarification', False)
            did_pivot = data.get('did_pivot', False)
            next_question = data.get('next_question', '')

            # 📊 LOG EVALUATION RESULTS
            logger.info(f"📊 GEMINI EVALUATION | Understanding: {score}/10 | Explainability: {explainability}/10 | Cheating: {is_cheating} | Off-Topic: {is_off_topic} | Needs Clarification: {needs_clarification} | Pivoted: {did_pivot}")
            if data.get('evidence_extracted'):
                logger.info(f"💬 Evidence Quote: \"{data.get('evidence_extracted')}\"")

            # Update local state based on LLM's decision
            if needs_clarification:
                self.turn_count -= 1  # Don't count clarification requests
            
            if did_pivot:
                self.current_topic_drill_depth = 0
                if score < 4:
                    logger.info(f"⚠️ WEAK/NO ANSWER | Score: {score}/10 | LLM pivoted to new skill")
                elif is_off_topic:
                    logger.warning(f"🚫 CANDIDATE WENT OFF-TOPIC | Score: {score}/10 | LLM pivoted")
            elif score >= 8:
                self.current_topic_drill_depth += 1
                logger.info(f"✅ STRONG ANSWER | Score: {score}/10 | Drill Depth: {self.current_topic_drill_depth}")
            else:
                logger.info(f"✅ VALID ANSWER | Score: {score}/10")

            if is_cheating:
                logger.warning(f"🚨 CHEATING SUSPECTED | Score: {score}/10 | Pause Duration: {pause_duration}s | Answer: \"{user_text[:100]}...\"")

            # 🚀 ASYNC BACKGROUND SAVE (Non-blocking) - Save BEFORE updating last_question
            # We're saving metrics for the question that was just answered
            if self.last_question_asked:  # Only save if there was a previous question
                asyncio.create_task(
                    self._save_background_metrics(self.last_question_asked, user_text, data, score)
                )

            # Update last question to the new question we're about to ask
            self.last_question_asked = next_question

            return next_question

        except Exception as e:
            logger.error(f"💥 Brain Pipeline Error: {e}", exc_info=True)
            return "That's interesting. Could you tell me more about your experience with that?"

    async def _save_background_metrics(self, question, answer, eval_data, score):
        try:
            # 🚀 FORCE empty list if Gemini sends null
            tech_missed = eval_data.get('technical_concepts_missed')
            if tech_missed is None:
                tech_missed = []

            await asyncio.to_thread(
                PerAnswerMetric.objects.create,
                session=self.session,
                question_asked=question,
                candidate_answer=answer,
                confidence_score=score,
                evidence_extracted=eval_data.get('evidence_extracted', '') or '',
                critique=eval_data.get('critique', '') or '',
                ideal_answer=eval_data.get('ideal_answer', '') or '',
                technical_concepts_missed=tech_missed, # 🚀 FIXED
                is_cheating_suspected=eval_data.get('is_cheating', False) or False,
                bias_flag=eval_data.get('bias_flag', False) or False
            )
            logger.info("✅ Background metrics saved to DB!")
        except Exception as e:
            logger.error(f"❌ Background Save Failed: {e}")