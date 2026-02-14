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
            # 1. ALWAYS Grade the previous response first
            if self.last_question_asked:
                history_context = await asyncio.to_thread(self._get_history_context)
                eval_data = await self._grade_answer(self.last_question_asked, user_text, pause_duration, history_context)
                
                score = eval_data.get('understanding_score', 0)
                explainability = eval_data.get('explainability_score', 0)
                needs_clarification = eval_data.get('needs_clarification', False)
                is_off_topic = eval_data.get('is_off_topic', False)
                is_cheating = eval_data.get('is_cheating', False)

                # 📊 LOG GEMINI'S EVALUATION RESULTS
                logger.info(f"📊 GEMINI EVALUATION | Understanding: {score}/10 | Explainability: {explainability}/10 | Cheating: {is_cheating} | Off-Topic: {is_off_topic} | Needs Clarification: {needs_clarification}")
                if eval_data.get('evidence_extracted'):
                    logger.info(f"💬 Evidence Quote: \"{eval_data.get('evidence_extracted')}\"")
                
                # Save the score so we can see how many skills they've actually answered
                asyncio.create_task(
                    self._save_background_metrics(self.last_question_asked, user_text, eval_data, score)
                )

            # 2. Increment turn count AFTER grading
            self.turn_count += 1

            # 3. SMART EXIT: Check Turn Count AND Session Health
            # We only end if we've hit max turns OR if the candidate is 
            # repeatedly failing to answer across different topics.
            if self.turn_count >= self.max_turns:
                logger.info(f"🏁 INTERVIEW COMPLETE | Total Turns: {self.turn_count}")
                return "FINISH_INTERVIEW: It's been great chatting with you! We've covered a wide range of topics. I'll pass my notes over to the team, and they'll be in touch. Do you have any final questions?"

            # 4. HANDLING "NOT REALLY" / WEAK ANSWERS / CHEATING
            # If they say "Not really," don't count it as a full technical turn. 
            # Pivot to a new skill and keep the interview going.
            if self.last_question_asked:
                if needs_clarification:
                    logger.info("🔄 Candidate requested clarification.")
                    self.turn_count -= 1  # Don't count clarification requests
                    directive = "The candidate asked for clarification. Rephrase the previous question simply."
                
                elif is_cheating:
                    logger.warning(f"🚨 CHEATING SUSPECTED | Score: {score}/10 | Pause Duration: {pause_duration}s | Answer: \"{user_text[:100]}...\"")
                    directive = "The candidate's answer sounded unnatural, like it was read from a script or ChatGPT. Call them out gently but firmly. Say something like 'Can you explain that in your own words?' or ask a highly specific follow-up about the exact mechanics of what they just read."
                
                elif is_off_topic:
                    logger.warning(f"🚫 CANDIDATE WENT OFF-TOPIC | Score: {score}/10")
                    directive = "The candidate gave a completely irrelevant answer. Be politely stern: 'Please keep your answers focused on the technical requirements for this role.' Then ask a new technical question about a DIFFERENT core skill."
                
                elif score < 3:
                    logger.info(f"⚠️ WEAK/NO ANSWER | Score: {score}/10 | Pivoting to new skill")
                    directive = "The candidate doesn't know this topic. Say something encouraging like 'No worries!' then PIVOT to a COMPLETELY DIFFERENT skill from the core skills list to give them another chance."
                
                else:
                    logger.info(f"✅ VALID ANSWER | Score: {score}/10")
                    if score >= 8:
                        self.current_topic_drill_depth += 1
                        if self.current_topic_drill_depth >= 2:
                            directive = "Strong answer! Acknowledge it briefly, then pivot to a DIFFERENT core skill."
                            self.current_topic_drill_depth = 0
                        else:
                            directive = "Great technical answer. Ask one quick follow-up to go slightly deeper, then we'll move on."
                    else:
                        directive = "The candidate gave a valid answer. Acknowledge it, then pivot to a new skill to gather more evidence."
                        self.current_topic_drill_depth = 0
            else:
                directive = "Start the technical interview. Ask an open-ended question about their experience with one of the core skills."

            # 5. Generate next question
            ai_spoken_response = await self._generate_next_question(directive, user_text)
            self.last_question_asked = ai_spoken_response
            
            return ai_spoken_response

        except Exception as e:
            logger.error(f"💥 Brain Pipeline Error: {e}", exc_info=True)
            return "That's interesting. Could you tell me more about your experience with that?"

    async def _grade_answer(self, question, answer, pause_duration, history_context):
        if not history_context:
            history_context = "No previous context. This is the first technical question."

        prompt = (
            f"--- CONTEXT OF CANDIDATE'S PREVIOUS ANSWERS ---\n"
            f"{history_context}\n"
            f"-----------------------------------------------\n\n"
            f"Current Question: {question}\nCandidate Answer: {answer}\n"
            f"Time taken before candidate started speaking: {pause_duration} seconds.\n\n"
            "Analyze this response like a Senior Lead Engineer. "
            "Evaluate the candidate on 'understanding_score' (technical accuracy 1-10) "
            "and 'explainability_score' (clarity 1-10). Extract a short exact quote as evidence.\n\n"
            "If the answer is weak, explain exactly what was missing in 'critique'. "
            "Provide a 10/10 'ideal_answer' for comparison that demonstrates what a strong response would include.\n"
            "List any specific 'technical_concepts_missed' (e.g., 'Indexing', 'N+1 queries', 'Memory management').\n\n"
            "CRITICAL GRADING RULES:\n"
            "- Score 8-10 (EXCELLENT): Mentions specific architectural decisions, real-world tools, or clear hands-on problem-solving. Reward practical engineering highly.\n"
            "- Score 5-7 (AVERAGE): Answer is technically correct but shallow, or they admit they only know the surface level.\n"
            "- Score 1-4 (POOR): Answer is completely incorrect, dodges the question, or shows zero technical knowledge.\n"
            "- is_off_topic: Set to TRUE if the answer is literal nonsense, a joke, or completely unrelated to software engineering. If true, score is 0.\n"
            "- is_cheating: Set to TRUE IF AND ONLY IF AT LEAST ONE of these is true:\n"
            "    A) The 'Time taken before speaking' is very high (e.g. > 8 seconds) AND the current answer sounds perfectly formatted, robotic, or read from a textbook.\n"
            "    B) There is a MASSIVE, unnatural spike in fluency, vocabulary, or knowledge compared to their 'Previous Answers'. For example: if they previously scored low or used very casual/broken language, but suddenly delivered a flawless, textbook definition.\n"
            "- needs_clarification: Set to TRUE ONLY if they explicitly ask you to repeat or clarify the question."
        )
        
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "understanding_score": {"type": "INTEGER"},
                    "explainability_score": {"type": "INTEGER"},
                    "evidence_extracted": {"type": "STRING"},
                    "critique": {"type": "STRING"},
                    "ideal_answer": {"type": "STRING"},
                    "technical_concepts_missed": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"}
                    },
                    "is_cheating": {"type": "BOOLEAN"},
                    "bias_flag": {"type": "BOOLEAN"},
                    "needs_clarification": {"type": "BOOLEAN"},
                    "is_off_topic": {"type": "BOOLEAN"} 
                }
            }
        )
        response = await asyncio.to_thread(
            self.client.models.generate_content, model=self.model_id, contents=prompt, config=config
        )
        return json.loads(response.text)

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

    async def _generate_next_question(self, directive, user_text):
        prompt = (
            f"Candidate said: '{user_text}'.\n\n"
            f"SYSTEM DIRECTIVE: {directive}\n\n"
            "CRITICAL FORMATTING RULES FOR YOUR RESPONSE:\n"
            "1. You are speaking out loud. Sound like a casual human.\n"
            "2. MAXIMUM 2 SENTENCES. Keep it extremely brief.\n"
            "3. NEVER write a paragraph. NEVER use bullet points.\n"
            "4. End with exactly ONE clear question."
        )
        response = await asyncio.to_thread(
            self.client.models.generate_content, model=self.model_id, contents=prompt
        )
        return response.text