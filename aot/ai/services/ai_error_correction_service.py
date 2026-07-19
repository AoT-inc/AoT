# coding=utf-8
import logging
import json
from typing import Optional, Dict, Any, List
from datetime import timedelta # Keep timedelta as it's used for calculations

from aot.databases.models.ai_error_feedback import AIErrorFeedback
from aot.databases.models import AIHistory, AIGlobalDecisions, AIDomainGlossary
from aot.utils.time_utils import utc_now # Import utc_now for timezone-aware datetime
# @ANCHOR: DECOUPLED_VIA_AI_CALLER_INTERFACE (IMP-011)
# AIAgentService top-level import removed (was unused). Per SBS-002_V2.

logger = logging.getLogger(__name__)

class AIErrorCorrectionService:
    """
    AI Error Correction & Self-Learning Service.
    Handles user feedback on AI errors and applies corrections at multiple levels.

    @phase active
    @stability unstable
    @dependency AIErrorFeedback, AIHistory, AIGlobalDecisions, AIDomainGlossary
    """

    @staticmethod
    def report_error(
        history_id: str,
        error_type: str,
        user_correction: str = None,
        severity: str = 'medium',
        user_comment: str = None,
        user_id: str = None
    ) -> Dict[str, Any]:
        """
        Report an AI error from user feedback.
        
        Args:
            history_id: AIHistory unique_id
            error_type: 'misinformation', 'inappropriate_action', 'hallucination', 'tool_misuse', 'other'
            user_correction: Correct information provided by user
            severity: 'low', 'medium', 'high', 'critical'
            user_comment: Additional user comments
            user_id: User who reported the error
            
        Returns:
            Dict with 'status', 'feedback_id', 'immediate_correction'
        """
        try:
            # Get the history entry
            history = AIHistory.query.filter_by(unique_id=history_id).first()
            if not history:
                return {'status': 'error', 'reason': 'history_not_found'}
            
            # Create error feedback record
            feedback = AIErrorFeedback(
                history_id=history_id,
                thread_id=history.thread_id,
                agent_id=history.agent_id,
                error_type=error_type,
                severity=severity,
                incorrect_response=history.response or '',
                user_correction=user_correction,
                user_comment=user_comment,
                context_snapshot=history.context_snapshot,
                prompt_used=history.prompt,
                reported_by=user_id or 'anonymous',
                status='reported'
            )
            feedback.save()
            
            logger.info(f"Error reported: {feedback.unique_id} (type={error_type}, severity={severity})")
            
            # Apply immediate correction if possible
            immediate_result = None
            if user_correction and severity in ['high', 'critical']:
                immediate_result = AIErrorCorrectionService.apply_immediate_correction(
                    history.thread_id,
                    feedback.unique_id
                )
            
            return {
                'status': 'success',
                'feedback_id': feedback.unique_id,
                'immediate_correction': immediate_result
            }
            
        except Exception as e:
            logger.error(f"Failed to report error: {e}", exc_info=True)
            return {'status': 'error', 'reason': str(e)}

    @staticmethod
    def apply_immediate_correction(
        thread_id: str,
        feedback_id: str
    ) -> Dict[str, Any]:
        """
        Apply immediate correction to the conversation thread.
        Adds correction to thread context and regenerates response.
        
        Args:
            thread_id: Conversation thread ID
            feedback_id: AIErrorFeedback unique_id
            
        Returns:
            Dict with 'status', 'corrected_response'
        """
        try:
            feedback = AIErrorFeedback.query.filter_by(unique_id=feedback_id).first()
            if not feedback:
                return {'status': 'error', 'reason': 'feedback_not_found'}
            
            # Mark incorrect response in thread history
            history = AIHistory.query.filter_by(unique_id=feedback.history_id).first()
            if history:
                # Add correction marker to the history
                if not history.metadata:
                    history.metadata = '{}'
                
                metadata = json.loads(history.metadata)
                metadata['corrected'] = True
                metadata['correction_id'] = feedback_id
                metadata['user_correction'] = feedback.user_correction
                history.metadata = json.dumps(metadata, ensure_ascii=False)
                history.save()
            
            # Add correction to global decisions for this thread
            correction_decision = AIGlobalDecisions(
                decision_text=f"CORRECTION: {feedback.user_correction}",
                context_summary=f"Error type: {feedback.error_type}. Original: {feedback.incorrect_response[:100]}",
                confidence_score=1.0,  # User corrections are 100% confident
                source='user_correction',
                tags=json.dumps(['error_correction', feedback.error_type, f'thread:{thread_id}'], ensure_ascii=False),
                status='confirmed'
            )
            correction_decision.save()
            
            # Update feedback status
            feedback.status = 'corrected'
            feedback.correction_applied = True
            feedback.resolved_at = utc_now() # Use utc_now
            feedback.save()
            
            logger.info(f"Immediate correction applied for feedback {feedback_id}")
            
            # Generate corrected response
            corrected_response = f"죄송합니다. 이전 응답을 정정하겠습니다.\n\n{feedback.user_correction}"
            
            return {
                'status': 'success',
                'corrected_response': corrected_response,
                'correction_id': correction_decision.unique_id
            }
            
        except Exception as e:
            logger.error(f"Failed to apply immediate correction: {e}", exc_info=True)
            return {'status': 'error', 'reason': str(e)}

    @staticmethod
    def update_global_knowledge(
        feedback_id: str,
        auto_approve: bool = False
    ) -> Dict[str, Any]:
        """
        Update global knowledge base with error correction.
        Adds to AIGlobalDecisions and optionally AIDomainGlossary.
        
        Args:
            feedback_id: AIErrorFeedback unique_id
            auto_approve: Automatically approve for knowledge base (admin only)
            
        Returns:
            Dict with 'status', 'knowledge_updated', 'glossary_updated'
        """
        try:
            feedback = AIErrorFeedback.query.filter_by(unique_id=feedback_id).first()
            if not feedback:
                return {'status': 'error', 'reason': 'feedback_not_found'}
            
            if not feedback.user_correction:
                return {'status': 'error', 'reason': 'no_correction_provided'}
            
            knowledge_updated = False
            glossary_updated = False
            
            # Add to global knowledge base
            if not feedback.added_to_knowledge_base:
                decision = AIGlobalDecisions(
                    decision_text=feedback.user_correction,
                    context_summary=f"User correction for {feedback.error_type}: {feedback.incorrect_response[:100]}",
                    confidence_score=0.9,
                    source='user_feedback',
                    tags=json.dumps(['error_correction', feedback.error_type], ensure_ascii=False),
                    status='confirmed' if auto_approve else 'pending'
                )
                decision.save()
                
                feedback.added_to_knowledge_base = True
                feedback.save()
                knowledge_updated = True
                
                logger.info(f"Added feedback {feedback_id} to global knowledge base")
            
            # Add to domain glossary if it's a definition/clarification
            if feedback.error_type in ['misinformation', 'hallucination']:
                # Extract key terms from correction
                # Simple heuristic: if correction contains "is" or "means"
                if any(word in feedback.user_correction.lower() for word in ['는', '은', 'is', 'means', '의미']):
                    if not feedback.added_to_glossary:
                        # Try to extract term and definition
                        # This is a simple implementation - can be improved with NLP
                        glossary = AIDomainGlossary(
                            term=feedback.incorrect_response[:50],  # Simplified
                            definition=feedback.user_correction,
                            category='user_correction',
                            priority=5,  # High priority
                            source='user_feedback',
                            is_active=True
                        )
                        glossary.save()
                        
                        feedback.added_to_glossary = True
                        feedback.save()
                        glossary_updated = True
                        
                        logger.info(f"Added feedback {feedback_id} to domain glossary")
            
            return {
                'status': 'success',
                'knowledge_updated': knowledge_updated,
                'glossary_updated': glossary_updated
            }
            
        except Exception as e:
            logger.error(f"Failed to update global knowledge: {e}", exc_info=True)
            return {'status': 'error', 'reason': str(e)}

    @staticmethod
    def analyze_error_patterns(
        days: int = 30,
        min_occurrences: int = 3
    ) -> Dict[str, Any]:
        """
        Analyze error patterns to identify systemic issues.
        
        Args:
            days: Number of days to analyze
            min_occurrences: Minimum occurrences to consider a pattern
            
        Returns:
            Dict with 'patterns', 'recommendations'
        """
        try:
            since = utc_now() - timedelta(days=days) # Use utc_now
            
            # Get all errors in the period
            errors = AIErrorFeedback.query.filter(
                AIErrorFeedback.reported_at >= since
            ).all()
            
            if not errors:
                return {'status': 'success', 'patterns': [], 'recommendations': []}
            
            # Analyze by error type
            type_counts = {}
            severity_counts = {}
            agent_errors = {}
            
            for error in errors:
                # Count by type
                type_counts[error.error_type] = type_counts.get(error.error_type, 0) + 1
                
                # Count by severity
                severity_counts[error.severity] = severity_counts.get(error.severity, 0) + 1
                
                # Count by agent
                if error.agent_id:
                    agent_errors[error.agent_id] = agent_errors.get(error.agent_id, 0) + 1
            
            # Identify patterns
            patterns = []
            
            for error_type, count in type_counts.items():
                if count >= min_occurrences:
                    patterns.append({
                        'type': 'error_type',
                        'category': error_type,
                        'count': count,
                        'percentage': round(count / len(errors) * 100, 1)
                    })
            
            for agent_id, count in agent_errors.items():
                if count >= min_occurrences:
                    patterns.append({
                        'type': 'agent_specific',
                        'agent_id': agent_id,
                        'count': count,
                        'percentage': round(count / len(errors) * 100, 1)
                    })
            
            # Generate recommendations
            recommendations = AIErrorCorrectionService._generate_recommendations(patterns, type_counts)
            
            return {
                'status': 'success',
                'total_errors': len(errors),
                'period_days': days,
                'patterns': patterns,
                'recommendations': recommendations,
                'summary': {
                    'by_type': type_counts,
                    'by_severity': severity_counts,
                    'by_agent': agent_errors
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze error patterns: {e}", exc_info=True)
            return {'status': 'error', 'reason': str(e)}

    @staticmethod
    def _generate_recommendations(patterns: List[Dict], type_counts: Dict) -> List[Dict[str, str]]:
        """Generate actionable recommendations based on error patterns."""
        recommendations = []
        
        # Recommendation for misinformation
        if type_counts.get('misinformation', 0) >= 3:
            recommendations.append({
                'issue': 'Frequent misinformation errors',
                'recommendation': 'Review and update context gathering logic. Consider adding data validation.',
                'priority': 'high'
            })
        
        # Recommendation for inappropriate actions
        if type_counts.get('inappropriate_action', 0) >= 3:
            recommendations.append({
                'issue': 'Frequent inappropriate action suggestions',
                'recommendation': 'Strengthen tool selection guidelines in prompts. Add explicit rules for information vs action requests.',
                'priority': 'high'
            })
        
        # Recommendation for hallucinations
        if type_counts.get('hallucination', 0) >= 3:
            recommendations.append({
                'issue': 'Frequent hallucinations',
                'recommendation': 'Add anti-hallucination instructions. Update domain glossary with supported features.',
                'priority': 'critical'
            })
        
        return recommendations

    @staticmethod
    def generate_training_data(
        min_severity: str = 'medium',
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Generate training data from error corrections for fine-tuning.
        
        Args:
            min_severity: Minimum severity to include ('low', 'medium', 'high', 'critical')
            limit: Maximum number of samples
            
        Returns:
            List of training samples in format: {'prompt', 'incorrect', 'correct'}
        """
        try:
            severity_order = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
            min_level = severity_order.get(min_severity, 1)
            
            # Get high-quality corrections
            feedbacks = AIErrorFeedback.query.filter(
                AIErrorFeedback.user_correction.isnot(None),
                AIErrorFeedback.status == 'learned'
            ).order_by(AIErrorFeedback.reported_at.desc()).limit(limit).all()
            
            training_data = []
            
            for feedback in feedbacks:
                if severity_order.get(feedback.severity, 0) < min_level:
                    continue
                
                sample = {
                    'prompt': feedback.prompt_used or '',
                    'incorrect_response': feedback.incorrect_response,
                    'correct_response': feedback.user_correction,
                    'error_type': feedback.error_type,
                    'severity': feedback.severity,
                    'context': feedback.context_snapshot
                }
                
                training_data.append(sample)
                
                # Mark as added to training data
                if not feedback.added_to_training_data:
                    feedback.added_to_training_data = True
                    feedback.save()
            
            logger.info(f"Generated {len(training_data)} training samples")
            
            return training_data
            
        except Exception as e:
            logger.error(f"Failed to generate training data: {e}", exc_info=True)
            return []
