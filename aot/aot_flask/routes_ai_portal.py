# coding=utf-8
"""
AI Portal Routes - Blueprint for AI Portal journey view API.

Provides (013/014):
- GET /api/v1/ai/portal/journey — full journey data payload
- POST /api/v1/ai/portal/recommendation/<id>/resolve — accept/dismiss recommendations

Provides (016 UX Redesign):
- POST /api/v1/ai/onboarding/setup — save Getting-to-Know setup, seed keywords
- GET /api/v1/ai/portal/status — AI Status snapshot (with interval refresh)
- DELETE /api/v1/ai/portal/status/snapshot — delete snapshot to force recalc
- PUT /api/v1/ai/portal/requirement — update user_requirement

Philosophy alignment:
- P1_Honesty: Natural language summaries explain what AI knows
- P2_Co_Growth: Recommendations extend from user interests
- P4_User_Agency: Users control recommendations and AI focus
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from aot.utils.time_utils import utc_now, api_iso
import json
import math

from aot.aot_flask.extensions import db
from aot.databases.models import (
    AIFacilityLearning, AIContextRecord, AIDomainGlossary, AITaskHistory,
    AIRecommendation, AIUserProfile, AIStatusSnapshot
)

blueprint = Blueprint('routes_ai_portal', __name__)


@blueprint.route('/api/v1/ai/portal/journey')
@login_required
def api_portal_journey():
    """
    Get full journey data for AI Portal mode_B.

    Returns:
    {
        onboarding: {
            completed: true,
            started_at: "ISO timestamp",
            interests: ["temperature", "humidity", ...],
            facility_type: "greenhouse"
        },
        clusters: [
            {
                interest: "temperature",
                label: "Temperature Management",
                summary: "...",
                confirmed_count: 3,
                pending_count: 1,
                last_updated: "ISO timestamp",
                growth_level: 3  (0-5)
            },
            ...
        ],
        recommendations: [
            {
                keyword: "CO2 Management",
                reason: "Related to your Temperature and Humidity focus",
                recommendation_id: "..."
            },
            ...
        ],
        recent_activity: [
            {
                text: "Learned a new term: Leaf Temperature",
                timestamp: "ISO timestamp"
            },
            ...
        ]
    }
    """
    facility_id = request.args.get('facility_id', '')
    if not facility_id:
        return jsonify({'error': 'facility_id required'}), 400

    response = {
        'onboarding': {},
        'clusters': [],
        'recommendations': [],
        'recent_activity': []
    }

    # Get facility learning record
    facility_learning = AIFacilityLearning.query.filter_by(facility_id=facility_id).first()
    if not facility_learning:
        return jsonify({'error': 'Facility not found'}), 404

    # Populate onboarding data
    response['onboarding'] = {
        'completed': facility_learning.onboarding_complete,
        'started_at': api_iso(facility_learning.learning_started_at),
        'interests': _parse_onboarding_interests(facility_learning),
        'facility_type': 'greenhouse'  # TODO: fetch from facility profile
    }

    # Get context records grouped by interest (keyword)
    context_records = AIContextRecord.query.filter_by(
        facility_id=facility_id
    ).all()

    clusters_map = _group_context_by_interest(context_records)
    response['clusters'] = list(clusters_map.values())

    # Get pending recommendations for this facility
    pending_recs = AIRecommendation.query.filter_by(
        facility_id=facility_id,
        status='pending'
    ).all()

    response['recommendations'] = [
        {
            'keyword': rec.keyword,
            'reason': rec.reason,
            'recommendation_id': rec.recommendation_id
        }
        for rec in pending_recs
    ]

    # If no pending recommendations, seed initial ones from interests
    if not response['recommendations']:
        response['recommendations'] = _seed_initial_recommendations(
            facility_id,
            response['onboarding']['interests']
        )

    # Phase 1: static placeholder activity
    response['recent_activity'] = _get_placeholder_activity()

    return jsonify(response)


@blueprint.route('/api/v1/ai/portal/recommendation/<recommendation_id>/resolve', methods=['POST'])
@login_required
def api_resolve_recommendation(recommendation_id):
    """
    Resolve (accept or dismiss) a recommendation.

    Body: { "status": "accepted" | "dismissed" }

    If status == "accepted":
    - Add keyword to facility's interest list
    - Create new knowledge cluster

    If status == "dismissed":
    - Mark as dismissed (won't be re-recommended)
    """
    data = request.get_json() or {}
    status = data.get('status')

    if status not in ['accepted', 'dismissed']:
        return jsonify({'error': 'Invalid status'}), 400

    # Find recommendation
    rec = AIRecommendation.query.filter_by(recommendation_id=recommendation_id).first()
    if not rec:
        return jsonify({'error': 'Recommendation not found'}), 404

    # Update status and resolved_at
    rec.status = status
    rec.resolved_at = datetime.utcnow()
    db.session.add(rec)
    db.session.commit()

    # If accepted, create context records or update interests
    if status == 'accepted':
        # TODO: Phase 3+ — create initial knowledge cluster entry
        pass

    return jsonify({'success': True, 'status': status, 'recommendation_id': recommendation_id})


def _parse_onboarding_interests(facility_learning):
    """
    Extract onboarding interest list from facility_learning.

    Phase 1: read from confirmations_json structure.
    Will be replaced with dedicated interest tracking in Phase 3.
    """
    try:
        confirmations = json.loads(facility_learning.confirmations_json or '{}')
        # Extract category keys as interests
        return list(confirmations.keys()) if confirmations else []
    except (json.JSONDecodeError, AttributeError):
        return []


def _group_context_by_interest(context_records):
    """
    Group AIContextRecord by keyword to form knowledge clusters.

    Returns: {
        "temperature": {
            interest: "temperature",
            label: "Temperature Management",
            summary: "...",
            confirmed_count: 3,
            pending_count: 1,
            last_updated: "...",
            growth_level: 3
        },
        ...
    }
    """
    clusters = {}

    for record in context_records:
        keyword = record.keyword or 'unknown'

        if keyword not in clusters:
            clusters[keyword] = {
                'interest': keyword,
                'label': _format_cluster_label(keyword),
                'summary': '',
                'confirmed_count': 0,
                'pending_count': 0,
                'last_updated': None,
                'growth_level': 0
            }

        cluster = clusters[keyword]

        # Count by status
        if record.context_state == 'user_confirmed':
            cluster['confirmed_count'] += 1
        elif record.context_state == 'pending':
            cluster['pending_count'] += 1

        # Track last update
        if record.updated_at:
            if not cluster['last_updated'] or record.updated_at > datetime.fromisoformat(cluster['last_updated']):
                cluster['last_updated'] = api_iso(record.updated_at)

    # Generate summaries and growth levels
    for cluster in clusters.values():
        cluster['summary'] = _generate_cluster_summary(cluster)
        cluster['growth_level'] = _calculate_growth_level(cluster['confirmed_count'])

    return clusters


def _format_cluster_label(keyword):
    """
    Format keyword as human-readable label.
    Example: "temperature" -> "Temperature Management"
    """
    label_map = {
        'temperature': 'Temperature Management',
        'humidity': 'Humidity Control',
        'irrigation': 'Irrigation Management',
        'lighting': 'Lighting Control',
        'co2': 'CO2 Management',
        'nutrients': 'Nutrient Management',
        'pest_management': 'Pest Management'
    }
    return label_map.get(keyword.lower(), keyword.title())


def _generate_cluster_summary(cluster):
    """
    Generate natural-language summary for a cluster.
    Phase 1: template-based. No LLM calls.
    """
    confirmed = cluster['confirmed_count']
    pending = cluster['pending_count']

    if confirmed == 0:
        return 'No confirmed data yet. AI is learning this domain.'

    summary = f'Optimal range and settings confirmed from {confirmed} data point{"s" if confirmed != 1 else ""}.'
    if pending > 0:
        summary += f' {pending} additional data point{"s" if pending != 1 else ""} awaiting review.'

    return summary


def _calculate_growth_level(confirmed_count):
    """
    Calculate growth level (0-5) based on confirmed count.
    0-0: 0 dots
    1-2: 1 dot
    3-4: 2 dots
    5-6: 3 dots
    7-8: 4 dots
    9+: 5 dots
    """
    if confirmed_count == 0:
        return 0
    elif confirmed_count <= 2:
        return 1
    elif confirmed_count <= 4:
        return 2
    elif confirmed_count <= 6:
        return 3
    elif confirmed_count <= 8:
        return 4
    else:
        return 5


def _seed_initial_recommendations(facility_id, interests):
    """
    Phase 3: Create initial recommendations based on onboarding interests.
    Rule-based mapping: interest -> related keywords.

    Returns list of recommendation dicts (created in DB).
    """
    recommendation_map = {
        'temperature': [
            {'keyword': 'CO2 Management', 'reason': 'Optimize CO2 levels for temperature-sensitive crops'},
        ],
        'humidity': [
            {'keyword': 'VPD Management', 'reason': 'Manage vapor pressure deficit alongside humidity'},
        ],
        'pest_management': [
            {'keyword': 'Biological Controls', 'reason': 'Integrate biological pest control methods'},
        ],
        'irrigation': [
            {'keyword': 'Soil Moisture Monitoring', 'reason': 'Complement irrigation with moisture sensing'},
        ],
        'lighting': [
            {'keyword': 'Light Spectrum Optimization', 'reason': 'Fine-tune light spectrum for crop response'},
        ]
    }

    created_recs = []
    for interest in interests:
        if interest in recommendation_map:
            for rec_data in recommendation_map[interest]:
                # Create AIRecommendation record
                new_rec = AIRecommendation(
                    facility_id=facility_id,
                    keyword=rec_data['keyword'],
                    reason=rec_data['reason'],
                    source_interests=json.dumps([interest]),
                    status='pending'
                )
                db.session.add(new_rec)
                db.session.flush()  # Ensure ID is generated

                created_recs.append({
                    'keyword': new_rec.keyword,
                    'reason': new_rec.reason,
                    'recommendation_id': new_rec.recommendation_id
                })

    db.session.commit()
    return created_recs[:3]  # Limit to 3 recommendations


def _get_placeholder_activity():
    """
    Phase 1: return static placeholder recent activity.
    Phase 3: replace with real AIHistory + AIDomainGlossary queries.
    """
    return [
        {
            'text': 'Learned a new term: Leaf Temperature (from your conversation)',
            'timestamp': api_iso(utc_now())
        },
        {
            'text': 'Updated optimal temperature range from SmartFarm API',
            'timestamp': api_iso(utc_now())
        }
    ]


# ============================================================
# 016 UX Redesign Endpoints
# ============================================================

# Keyword map seeded on onboarding completion
_PRESET_KEYWORD_MAP = {
    'outdoor_farming':  ['crop_management', 'weather', 'soil', 'irrigation', 'pest_management'],
    'greenhouse':       ['temperature', 'humidity', 'co2', 'pest_management', 'energy'],
    'sports_facility':  ['facility_usage', 'maintenance', 'scheduling', 'visitor_management'],
    'park':             ['visitor_flow', 'maintenance', 'seasonal_planning', 'safety'],
    'transportation':   ['traffic_flow', 'incident_management', 'maintenance', 'scheduling'],
}


@blueprint.route('/api/v1/ai/onboarding/setup', methods=['POST'])
@login_required
def api_onboarding_setup():
    """
    016: Save Getting-to-Know setup and complete onboarding.

    Body: { preset: str, user_requirement: str|null }

    Actions:
    - Save facility_preset and user_requirement to AIUserProfile
    - Set onboarding_completed = True, onboarding_completed_at = now
    - Seed initial AIContextRecord keywords from preset keyword_map
    """
    data = request.get_json() or {}
    preset = data.get('preset', '').strip()
    user_requirement = data.get('user_requirement') or None

    if preset not in _PRESET_KEYWORD_MAP:
        return jsonify({'error': 'Invalid preset'}), 400

    # Get or create AIUserProfile for current user
    profile = AIUserProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = AIUserProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.flush()

    profile.facility_preset = preset
    profile.user_requirement = user_requirement
    profile.onboarding_completed = True
    profile.onboarding_completed_at = datetime.utcnow()

    # Seed AIContextRecord keywords from preset map (only if none exist yet)
    facility_id = request.json.get('facility_id') or _resolve_facility_id()
    if facility_id:
        existing_count = AIContextRecord.query.filter_by(
            facility_id=facility_id
        ).count()
        if existing_count == 0:
            for keyword in _PRESET_KEYWORD_MAP[preset]:
                seed_record = AIContextRecord(
                    facility_id=facility_id,
                    parameter_name=keyword,
                    value='seeded_from_preset',
                    source='onboarding_preset',
                    context_state='system_generated',
                    created_by='onboarding'
                )
                db.session.add(seed_record)

    db.session.commit()
    return jsonify({'success': True})


def _resolve_facility_id():
    """Resolve facility_id from Misc settings."""
    try:
        from aot.databases.models import Misc
        misc = Misc.query.first()
        if misc and hasattr(misc, 'default_facility_id'):
            return misc.default_facility_id
    except Exception:
        pass
    return None


# ----------------------------------------------------------------
# Snapshot refresh interval logic
# ----------------------------------------------------------------

def _get_refresh_interval_days(week_number):
    """
    Return the cache validity interval in days based on onboarding week_number.
    week 1: 1 day, week 2: 2 days, weeks 3-7: 7 days, week 8+: 30 days
    """
    if week_number <= 1:
        return 1
    elif week_number == 2:
        return 2
    elif week_number <= 7:
        return 7
    else:
        return 30


def _compute_week_number(onboarding_completed_at):
    """Calculate current week number since onboarding."""
    if not onboarding_completed_at:
        return 1
    days_elapsed = (datetime.utcnow() - onboarding_completed_at).days
    return math.floor(days_elapsed / 7) + 1


def _build_status_snapshot(facility_id):
    """
    Build the status snapshot dict from live DB data.

    Returns:
        {
            learning_progress: {total, confirmed, pending},
            keywords: [{keyword, confirmed_count}, ...],
            features: [{action_type, count}, ...],
            calculated_at: ISO string
        }
    """
    # Learning progress counts
    records = AIContextRecord.query.filter_by(
        facility_id=facility_id
    ).all()

    total = len(records)
    confirmed = sum(1 for r in records if r.context_state == 'user_confirmed')
    pending = sum(1 for r in records if r.context_state == 'pending')

    # Key keywords: group by parameter_name, count user_confirmed
    kw_counts = {}
    for r in records:
        kw = r.parameter_name or 'unknown'
        if kw not in kw_counts:
            kw_counts[kw] = 0
        if r.context_state == 'user_confirmed':
            kw_counts[kw] += 1

    keywords = sorted(
        [{'keyword': k, 'confirmed_count': v} for k, v in kw_counts.items()],
        key=lambda x: x['confirmed_count'],
        reverse=True
    )[:10]

    # Frequently used features: message_type distribution from AIHistory
    features = _get_frequent_features(facility_id)

    return {
        'learning_progress': {'total': total, 'confirmed': confirmed, 'pending': pending},
        'keywords': keywords,
        'features': features,
        'calculated_at': api_iso(utc_now())
    }


def _get_frequent_features(facility_id):
    """
    Approximate frequently used features from AIHistory message_type distribution.
    Returns top 5 [{action_type, count}].
    """
    try:
        from aot.databases.models import AIHistory
        from sqlalchemy import func
        rows = (
            db.session.query(AIHistory.message_type, func.count(AIHistory.id).label('cnt'))
            .group_by(AIHistory.message_type)
            .order_by(func.count(AIHistory.id).desc())
            .limit(5)
            .all()
        )
        return [{'action_type': r.message_type, 'count': r.cnt} for r in rows]
    except Exception:
        return []


@blueprint.route('/api/v1/ai/portal/status')
@login_required
def api_portal_status():
    """
    016: Get AI Status snapshot for a facility.
    Recalculates if the snapshot is older than the interval for the user's week.

    Query params: facility_id (required)
    """
    facility_id = request.args.get('facility_id', '').strip()
    if not facility_id:
        return jsonify({'error': 'facility_id required'}), 400

    # Determine week_number from current user's profile
    profile = AIUserProfile.query.filter_by(user_id=current_user.id).first()
    week_number = _compute_week_number(
        profile.onboarding_completed_at if profile else None
    )
    interval_days = _get_refresh_interval_days(week_number)

    # Check cached snapshot
    snapshot_rec = AIStatusSnapshot.query.filter_by(facility_id=facility_id).first()
    needs_refresh = True
    if snapshot_rec and snapshot_rec.created_at:
        age = (datetime.utcnow() - snapshot_rec.created_at).total_seconds() / 86400
        if age < interval_days:
            needs_refresh = False

    if needs_refresh:
        snap_data = _build_status_snapshot(facility_id)
        if snapshot_rec:
            snapshot_rec.snapshot_data = json.dumps(snap_data)
            snapshot_rec.created_at = datetime.utcnow()
            snapshot_rec.week_number = week_number
        else:
            snapshot_rec = AIStatusSnapshot(
                facility_id=facility_id,
                snapshot_data=json.dumps(snap_data),
                week_number=week_number
            )
            db.session.add(snapshot_rec)
        db.session.commit()

    try:
        snap_data = json.loads(snapshot_rec.snapshot_data)
    except (json.JSONDecodeError, AttributeError):
        snap_data = _build_status_snapshot(facility_id)

    return jsonify({'success': True, 'data': snap_data, 'week_number': week_number})


@blueprint.route('/api/v1/ai/portal/status/snapshot', methods=['DELETE'])
@login_required
def api_delete_status_snapshot():
    """
    016: Delete AIStatusSnapshot records for facility — forces fresh calculation on next load.
    Query params: facility_id (required)
    """
    facility_id = request.args.get('facility_id', '').strip()
    if not facility_id:
        return jsonify({'error': 'facility_id required'}), 400

    deleted = AIStatusSnapshot.query.filter_by(facility_id=facility_id).delete()
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted})


@blueprint.route('/api/v1/ai/portal/requirement', methods=['PUT'])
@login_required
def api_update_requirement():
    """
    016: Update user_requirement for the current user's AIUserProfile.

    Body: { user_requirement: str }
    """
    data = request.get_json() or {}
    user_requirement = data.get('user_requirement', '').strip() or None

    profile = AIUserProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        return jsonify({'error': 'Profile not found'}), 404

    profile.user_requirement = user_requirement
    db.session.commit()
    return jsonify({'success': True})
