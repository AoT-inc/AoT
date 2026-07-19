import json
import logging
from aot.databases.models import db, AIDomainGlossary, AIUserProfile
from datetime import datetime

logger = logging.getLogger(__name__)

class AILearningService:
    """
    Handles AI learning, user proficiency tracking, and domain glossary management.
    Intercepts AI responses for user approval requirements.

    @phase active
    @stability unstable
    @dependency AIDomainGlossary, AIUserProfile
    """
    @staticmethod
    def process_ai_response(ai_text_reply: str) -> dict:
        """
        AI 응답 내 사용자 승인이 필요한 미지어가 있는지 감지하고 인터셉트
        """
        if not ai_text_reply:
            return {"text": ai_text_reply, "requires_action": False}
            
        if "___ACTION_REQUIRED___:" in ai_text_reply:
            try:
                parts = ai_text_reply.split("___ACTION_REQUIRED___:")
                message_for_user = parts[0].strip()
                action_data_str = parts[1].strip()
                
                # Cleanup potential trailing braces or markdown
                if "}" in action_data_str:
                    action_data_str = action_data_str[:action_data_str.rfind("}")+1]
                
                action_data = json.loads(action_data_str)
                a_type = action_data.get("type")
                
                if a_type == "term_approval":
                    term = action_data.get("term")
                    guessed_definition = action_data.get("guessed_definition")
                    
                    if term and guessed_definition:
                        # 1. 임시 지식 DB 등록 (상태: pending)
                        existing_term = AIDomainGlossary.query.filter_by(term=term).first()
                        if not existing_term:
                            new_term = AIDomainGlossary(
                                term=term, 
                                definition=guessed_definition, 
                                source="Web Search (Auto)", 
                                status="pending"
                            )
                            db.session.add(new_term)
                            db.session.commit()
                            term_id = new_term.id
                        else:
                            term_id = existing_term.id
                        
                        return {
                            "text": message_for_user,
                            "requires_action": True,
                            "action_type": "KNOWLEDGE_APPROVAL",
                            "payload": {
                                "term_id": term_id, 
                                "term": term, 
                                "definition": guessed_definition
                            }
                        }
                elif a_type == "confirmation":
                    return {
                        "text": message_for_user,
                        "requires_action": True,
                        "action_type": "USER_CONFIRMATION",
                        "payload": action_data
                    }
                
                # Default for other action types: just strip the marker
                return {"text": message_for_user, "requires_action": False}

            except Exception as e:
                logger.exception("Error processing AI learning response")
                # Fallback: Still try to return the text without the marker even if JSON parsing fails
                clean_text = ai_text_reply.split("___ACTION_REQUIRED___:")[0].strip()
                return {"text": clean_text, "requires_action": False}
        
        return {"text": ai_text_reply, "requires_action": False}

    @staticmethod
    def get_active_glossary():
        """
        승인된 도메인 단어장 목록 조회 (Context 주입용)
        """
        try:
            approved_terms = AIDomainGlossary.query.filter_by(status="approved", is_active=True).all()
            return [{"term": record.term, "definition": record.definition} for record in approved_terms]
        except Exception as e:
            logger.exception("Error fetching domain glossary")
            return []

    @staticmethod
    def get_user_profile(user_id: int) -> AIUserProfile:
        """
        Retrieves or creates an AI interaction profile for the user.
        """
        if not user_id:
            return None
        try:
            profile = AIUserProfile.query.filter_by(user_id=user_id).first()
            if not profile:
                profile = AIUserProfile(user_id=user_id)
                db.session.add(profile)
                db.session.commit()
            return profile
        except Exception:
            logger.exception(f"Error getting user profile for ID: {user_id}")
            return None

    @staticmethod
    def analyze_user_proficiency(user_id: int, message: str):
        """
        Analyzes the user's message to update their technical proficiency score.
        """
        if not user_id or not message:
            return

        profile = AILearningService.get_user_profile(user_id)
        if not profile:
            return

        score_delta = 0
        msg_lower = message.lower()

        # Technical/Advanced keywords (+2 points each)
        tech_keywords = [
            'pid', 'action', 'json', 'interface', 'api', 'manifest', 
            'node_id', 'unique_id', 'mqtt', 'topic', 'calibration', 
            'trigger', 'conditional', '센서', '제어', '데이터', '파라미터'
        ]
        
        # Beginner/Clarification keywords (+1 beginner focus, doesn't directly decrease score 
        # but prevents rapid advancement if mixed)
        beginner_keywords = [
            '어떻게', '무엇', '도와줘', '도움말', '모르겠', '설명', '방법',
            'how to', 'help', 'what is'
        ]

        for word in tech_keywords:
            if word in msg_lower:
                score_delta += 2
        
        for word in beginner_keywords:
            if word in msg_lower:
                score_delta -= 1 # Slows down advancement for basic queries

        if score_delta != 0:
            profile.proficiency_score = max(0, profile.proficiency_score + score_delta)
            
            # Update levels based on score
            old_level = profile.proficiency_level
            if profile.proficiency_score < 10:
                profile.proficiency_level = 'beginner'
            elif profile.proficiency_score < 30:
                profile.proficiency_level = 'intermediate'
            else:
                profile.proficiency_level = 'advanced'
            
            if old_level != profile.proficiency_level:
                logger.info(f"User {user_id} proficiency level changed: {old_level} -> {profile.proficiency_level}")

            db.session.commit()
