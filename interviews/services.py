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
        self.language = rubric.get('primary_language', 'General Programming')
        self.level = rubric.get('experience_level', 'Mid-Level')
        self.core_skills = rubric.get('core_skills', ['Core Concepts'])
        self.focus = rubric.get('evaluation_focus', ['Understanding'])
        
        self.turn_count = 0
        self.max_turns = 6 
        self.last_question_asked = None
        
        # 🚀 1. NEW: TRACK HOW DEEP WE ARE IN A SINGLE TOPIC
        self.current_topic_drill_depth = 0

        config = types.GenerateContentConfig(
            system_instruction=self.get_instructions(),
            temperature=0.7,
        )
        self.chat = self.client.chats.create(model=self.model_id, config=config)

    def get_instructions(self):
        skills_str = ", ".join(self.core_skills)
        focus_str = ", ".join(self.focus)
        return (
            f"You are a dynamic technical interviewer hiring a {self.level} {self.session.job.title}. "
            f"Candidate: {self.session.candidate_name}. "
            f"Primary Language: {self.language}. "
            f"Core Skills to cover: {skills_str}. "
            f"Evaluation Focus: {focus_str}. "
            "INSTRUCTIONS: "
            "1. Do not interrogate. Have a natural, flowing conversation. "
            "2. If they don't know a specific skill, pivot smoothly to the next skill in the list. "
            "3. Ask exactly ONE question at a time. Keep it conversational and under 2 sentences."
        )

    async def generate_intro(self):
        logger.info("🎬 Generating Interview Intro")
        prompt = (
            f"SYSTEM COMMAND: The interview has just started. Greet {self.session.candidate_name}. "
            f"Introduce yourself as the AI Interviewer for the {self.session.job.title} role. "
            f"Briefly mention we'll be discussing {self.language} and core backend skills. "
            "End by asking if they are ready to begin. Keep it natural and under 3 short sentences."
        )
        response = await asyncio.to_thread(self.chat.send_message, prompt)
        
        self.session.current_stage = 'technical'
        await asyncio.to_thread(self.session.save)
        return response.text

    async def get_answer(self, user_text):
        try:
            self.turn_count += 1

            if self.turn_count > self.max_turns:
                return "We've covered some great ground today. I have all the information I need. Do you have any questions for me before we wrap up?"

            if self.last_question_asked:
                eval_data = await self._grade_answer(self.last_question_asked, user_text)
                score = eval_data.get('understanding_score', 0)
                needs_clarification = eval_data.get('needs_clarification', False)

                if needs_clarification:
                    logger.info("🔄 Candidate requested clarification. Rephrasing.")
                    self.turn_count -= 1 
                    directive = (
                        "The candidate didn't hear or didn't understand the question. "
                        "Do not change the topic. Politely rephrase the previous question "
                        "in a much simpler, clearer way."
                    )
                else:
                    asyncio.create_task(
                        self._save_background_metrics(self.last_question_asked, user_text, eval_data, score)
                    )

                    # 🚀 2. NEW: THE SMART PIVOT & DRILL LOGIC
                    if score >= 8:
                        self.current_topic_drill_depth += 1
                        
                        if self.current_topic_drill_depth >= 3:
                            logger.info(f"✅ Max depth reached (Score: {score}). Forcing pivot.")
                            directive = "You have dug deep enough into this specific topic. Acknowledge their strong answer briefly, then PIVOT smoothly to a COMPLETELY DIFFERENT core skill from the required list."
                            self.current_topic_drill_depth = 0 # Reset for the new topic
                        else:
                            logger.info(f"✅ Good understanding (Score: {score}). Going deeper (Depth {self.current_topic_drill_depth}/3).")
                            directive = "The candidate gave a strong answer. Ask a quick, concise follow-up question to dive slightly deeper into the technical mechanics of what they just said."
                    
                    elif score >= 5:
                        logger.info(f"⚠️ Average/Practical understanding (Score: {score}). Pivoting gracefully.")
                        directive = "The candidate has practical/surface-level knowledge but might not know the deep internals. Say something like 'That makes sense' and PIVOT smoothly to a different core skill to avoid interrogating them."
                        self.current_topic_drill_depth = 0 # Reset
                    
                    else:
                        logger.info(f"❌ Struggled (Score: {score}). Pivoting.")
                        directive = "The candidate struggled with that concept. DO NOT repeat the question. Be encouraging and pivot smoothly to a completely different core skill."
                        self.current_topic_drill_depth = 0 # Reset
            else:
                directive = "Start the technical interview. Ask an open-ended question about their experience with one of the core skills."

            ai_spoken_response = await self._generate_next_question(directive, user_text)
            self.last_question_asked = ai_spoken_response
            
            return ai_spoken_response

        except Exception as e:
            logger.error(f"💥 Brain Pipeline Error: {e}", exc_info=True)
            return "Could you elaborate on that?"

    async def _grade_answer(self, question, answer):
        # 🚀 3. NEW: THE "HONEST DEVELOPER" GRACE RULE
        prompt = (
            f"Question: {question}\nCandidate Answer: {answer}\n"
            "Evaluate the candidate on 'understanding_score' (technical accuracy 1-10) "
            "and 'explainability_score' (clarity 1-10). Extract a short exact quote as evidence. \n\n"
            "GRADING RULES:\n"
            "- Score 8-10: Deep, accurate, technical knowledge.\n"
            "- Score 5-7: Practical knowledge. (CRITICAL: If the candidate honestly admits they only know how to use the tool practically/on the surface but don't know the deep architecture, give them a 5, 6, or 7. Do NOT fail them for being honest about practical limitations).\n"
            "- Score 1-4: Completely incorrect or absolutely zero knowledge.\n"
            "- Set 'needs_clarification' to true (scores to 0) ONLY if they ask you to repeat the question."
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "understanding_score": {"type": "INTEGER"},
                    "explainability_score": {"type": "INTEGER"},
                    "evidence_extracted": {"type": "STRING"},
                    "is_cheating": {"type": "BOOLEAN"},
                    "bias_flag": {"type": "BOOLEAN"},
                    "needs_clarification": {"type": "BOOLEAN"}
                }
            }
        )
        response = await asyncio.to_thread(
            self.client.models.generate_content, model=self.model_id, contents=prompt, config=config
        )
        return json.loads(response.text)

    async def _save_background_metrics(self, question, answer, eval_data, score):
        try:
            await asyncio.to_thread(
                PerAnswerMetric.objects.create,
                session=self.session,
                question_asked=question,
                candidate_answer=answer,
                confidence_score=score,
                evidence_extracted=eval_data.get('evidence_extracted', ''),
                is_cheating_suspected=eval_data.get('is_cheating', False),
                bias_flag=eval_data.get('bias_flag', False)
            )
            if score >= 7:
                await asyncio.to_thread(
                    EvidenceSnippet.objects.create,
                    session=self.session,
                    metric_name="Core Competency", 
                    snippet=eval_data.get('evidence_extracted', ''),
                    confidence_score=score
                )
            logger.info("✅ Background metrics saved to DB!")
        except Exception as e:
            logger.error(f"❌ Background Save Failed: {e}")

    async def _generate_next_question(self, directive, user_text):
        # 🚀 4. NEW: STRICT BREVITY ENFORCEMENT
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