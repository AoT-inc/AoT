# coding=utf-8
"""
routes_ai_library.py — AI Library Blueprint.

Provides the /ai/library page and REST API for managing AIContextSource entries.
Each source is an external data connection that periodically injects knowledge
into the AI context pipeline (AIContextRecord).
"""
import json
import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required, current_user

from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_general
from aot.databases.models import AIContextSource, Misc
from aot.ai.services.context_source_service import sync_source
from aot.ai.services import knowledge_promotion_service

logger = logging.getLogger(__name__)

# @ANCHOR: AI_LIBRARY_BLUEPRINT
ai_library_bp = Blueprint('routes_ai_library', __name__)


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

# Library presets shown in the Add dropdown.
# is_system=True  → system-provided ext clients (aot/ai/context/ext/)
# is_system=False → user-configured custom sources
#
# Info-block fields (2026-07-19, rendered at the top of the settings modal —
# same layout contract as the input/output options modals' info header):
#   description_ko : what this source is (shown as the italic message block)
#   usage          : one-line how-to (shown as the '사용법:' line)
#   url_source     : the ORIGINAL data source / service site ('원본' link)
#   url_api_key    : where to issue the API key ('API 키 발급' link), if any
# The English 'description' is kept for any existing consumer; the modal
# prefers description_ko.
LIBRARY_PRESETS = {
    # ------------------------------------------------------------------
    # System Libraries — aot/ai/context/ext/
    # ------------------------------------------------------------------
    'ext_smartfarm': {
        'label': 'SmartFarm Productivity (EXT-KR-01)',
        'description': 'RDA SmartFarm optimal setpoints: temperature, humidity, CO2, light per crop/stage.',
        'description_ko': '농촌진흥청(RDA) 스마트팜 생산성 공공데이터 — 작물·생육단계별 '
                          '최적 온도/습도/CO2/광량 설정값을 제공합니다. 동기화된 값은 AI가 '
                          '환경 관련 질문에 권위 근거([권위] 태그)로 인용합니다.',
        'usage': '공공데이터포털에서 API 키를 발급받아 아래에 입력하고 재배 작물을 지정한 뒤 '
                 '활성화하세요. 이후 7일 주기로 자동 동기화됩니다.',
        'url_source': 'https://www.data.go.kr/data/15121053/openapi.do',
        'url_api_key': 'https://www.data.go.kr',
        'source_type': 'rest_api',
        'is_system': True,
        'ext_client': 'smartfarm_client.ExtSmartfarmClient',
        'auth_key_name': 'RDA_API_KEY',
        'sync_interval_min': 10080,  # 7 days
    },
    'ext_nongsaro': {
        'label': 'Nongsaro Cultivation Guide (EXT-KR-02)',
        'description': 'Crop cultivation guides and weekly farming calendar from Nongsaro Open API.',
        'description_ko': '농사로(농촌진흥청 농업기술포털) 오픈API — 작물별 재배 가이드와 '
                          '주간 농작업 캘린더를 제공합니다. AI가 재배 방법 질문에 권위 '
                          '근거([권위] 태그)로 인용합니다.',
        'usage': '농사로 오픈API에서 키를 발급받아 아래에 입력하고 활성화하세요. '
                 '이후 1일 주기로 자동 동기화됩니다.',
        'url_source': 'https://www.nongsaro.go.kr',
        'url_api_key': 'https://api.nongsaro.go.kr',
        'source_type': 'rest_api',
        'is_system': True,
        'ext_client': 'nongsaro_client.NongsaroClient',
        'auth_key_name': 'NONGSARO_API_KEY',
        'sync_interval_min': 1440,  # 1 day
    },
    'ext_pest': {
        'label': 'Pest Management Alerts (EXT-KR-03)',
        'description': 'Real-time pest and disease alerts from the National Crop Protection Management System.',
        'description_ko': '국가농작물병해충관리시스템(NCPMS) — 작물별 병해충 발생 경보와 '
                          '방제 정보를 제공합니다. 경보는 시효성이 있어 6시간이 지나면 '
                          'AI 인용에서 자동 제외됩니다.',
        'usage': 'NCPMS에서 API 키를 발급받아 아래에 입력하고 활성화하세요. '
                 '이후 6시간 주기로 자동 동기화됩니다.',
        'url_source': 'https://ncpms.rda.go.kr',
        'url_api_key': 'https://ncpms.rda.go.kr',
        'source_type': 'rest_api',
        'is_system': True,
        'ext_client': 'pest_management_client.PestManagementClient',
        'auth_key_name': 'NCPMS_API_KEY',
        'sync_interval_min': 360,  # 6 hours
    },
    'smartfarmkorea': {
        'label': 'SmartFarmKorea Big Data (EXT-KR-04)',
        'description': 'Real farm environment/growth measurement data from ~2,300 participating '
                       'farms, via the SmartFarmKorea data mart. Pick which operations to sync.',
        'description_ko': '스마트팜코리아(농림수산식품교육문화정보원) 스마트팜 빅데이터 — '
                          '전국 약 2,300개 참여 농가의 환경·생육 실측 데이터를 제공합니다. '
                          'RDA 스마트팜(EXT-KR-01)이 "권장 설정값"이라면, 이쪽은 실제 농가에서 '
                          '측정된 "실측 데이터"입니다. 아래에서 필요한 항목만 선택해 지식으로 '
                          '등록하세요.',
        'usage': '스마트팜코리아에서 API 서비스 키를 발급받아 입력하고, 등록할 항목을 고른 뒤 '
                 "'농가 불러오기'로 지역·작물을 보고 본인 농가를, 이어서 작기명을 보고 작기를 "
                 '선택하세요. 사용자ID·작기번호 같은 코드는 자동으로 채워지므로 직접 입력할 '
                 '필요가 없습니다.',
        'url_source': 'https://smartfarmkorea.net/openApi/openApiList.do?menuId=M1104030101',
        'url_api_key': 'https://smartfarmkorea.net/openApi/openApiList.do?menuId=M1104030101',
        'source_type': 'rest_api',
        'is_system': True,
        # No EXT_CLIENT_MAP entry — @ANCHOR: SMARTFARMKOREA_DIGEST in
        # context_source_service.py routes this preset_key directly, since its
        # sync writes AIKnowledgeChunk chunks (heterogeneous per-operation
        # schema), not the single-shape AIContextRecord bridge the
        # EXT_CLIENT_MAP presets use.
        'ext_client': 'smartfarmkorea_client',
        'auth_key_name': 'SMARTFARMKOREA_SERVICE_KEY',
        'sync_interval_min': 1440,  # 1 day
        'multi_operation': True,  # UI: render the 7-operation checklist, not a single config form
    },
    'smartfarmkorea_outdoor': {
        'label': 'SmartFarmKorea Big Data — Outdoor Field (EXT-KR-05)',
        'description': 'Real farm environment/growth measurement data from ~1,650 open-field '
                       '(non-greenhouse) farms, via the SmartFarmKorea data mart. Pick which '
                       'operations to sync.',
        'description_ko': '스마트팜코리아(농림수산식품교육문화정보원) 노지 빅데이터 — '
                          '전국 약 1,650개 노지(비닐하우스가 아닌 노지 재배) 농가의 환경·생육 '
                          '실측 데이터를 제공합니다. 시설원예(EXT-KR-04)와 같은 기관·같은 API '
                          '방식이지만 별도 서비스(별도 API 키가 필요할 수 있음)이며, 대상 작물도 '
                          '마늘·양파·블루베리로 다릅니다. 아래에서 필요한 항목만 선택해 지식으로 '
                          '등록하세요.',
        'usage': '스마트팜코리아 노지 빅데이터 페이지에서 API 서비스 키를 발급받아 입력하고, '
                 "등록할 항목을 고른 뒤 '농가 불러오기'로 지역·작물을 보고 본인 농가를, 이어서 "
                 '작기명을 보고 작기를 선택하세요. 사용자ID·작기번호 같은 코드는 자동으로 '
                 '채워지므로 직접 입력할 필요가 없습니다.',
        'url_source': 'https://smartfarmkorea.net/openApi/openApiList.do?menuId=M11040302',
        'url_api_key': 'https://smartfarmkorea.net/openApi/openApiList.do?menuId=M11040302',
        'source_type': 'rest_api',
        'is_system': True,
        # Same routing rationale as 'smartfarmkorea' above — see
        # @ANCHOR: SMARTFARMKOREA_DIGEST in context_source_service.py, which
        # dispatches both preset_keys through the same client with a
        # different operations dict (OUTDOOR_OPERATIONS).
        'ext_client': 'smartfarmkorea_client',
        'auth_key_name': 'SMARTFARMKOREA_OUTDOOR_SERVICE_KEY',
        'sync_interval_min': 1440,  # 1 day
        'multi_operation': True,
    },
    'smartfarmkorea_livestock': {
        'label': 'SmartFarmKorea Big Data — Livestock (EXT-KR-06)',
        'description': 'Real farm production/breeding measurement data from ~348 livestock '
                       'farms (dairy/swine/poultry/hanwoo), via the SmartFarmKorea data mart. '
                       'Data collection ended in 2022 — this is a historical archive, not a '
                       'live-growing feed. Pick which operations to sync.',
        'description_ko': '스마트팜코리아(농림수산식품교육문화정보원) 축산 빅데이터 — '
                          '전국 약 348개 축산 농가(낙농·양돈·양계·한우)의 생산·번식 실측 '
                          '데이터를 제공합니다. 시설원예/노지와 같은 기관·같은 API 방식이지만 '
                          '별도 서비스(별도 API 키가 필요할 수 있음)입니다. 2022년에 데이터 '
                          '수집이 종료되어 새 기록은 더 늘지 않는 과거 축적 데이터입니다. '
                          '다른 두 데이터셋과 달리 사용자ID·시설ID 등 사전 조회값이 필요 '
                          '없이 조회 기간(시작일·종료일)만 있으면 바로 조회됩니다. 아래에서 '
                          '필요한 항목만 선택해 지식으로 등록하세요.',
        'usage': '스마트팜코리아 축산 빅데이터 페이지에서 API 서비스 키를 발급받아 입력하고, '
                 '필요한 항목(낙농/양돈/양계/한우)을 선택한 뒤 조회 기간(시작일·종료일, '
                 'YYYYMMDD 형식)을 입력하고 활성화하세요.',
        'url_source': 'https://smartfarmkorea.net/openApi/openApiList.do?menuId=M11040303',
        'url_api_key': 'https://smartfarmkorea.net/openApi/openApiList.do?menuId=M11040303',
        'source_type': 'rest_api',
        'is_system': True,
        # Same routing rationale as 'smartfarmkorea'/'smartfarmkorea_outdoor'
        # above — see @ANCHOR: SMARTFARMKOREA_DIGEST in
        # context_source_service.py, which dispatches all three preset_keys
        # through the same client with a different operations dict
        # (LIVESTOCK_OPERATIONS).
        'ext_client': 'smartfarmkorea_client',
        'auth_key_name': 'SMARTFARMKOREA_LIVESTOCK_SERVICE_KEY',
        'sync_interval_min': 1440,  # 1 day (harmless even though the dataset is frozen)
        'multi_operation': True,
    },
    # ------------------------------------------------------------------
    # Custom Sources — user-configured
    # ------------------------------------------------------------------
    'rest_api': {
        'label': 'REST API',
        'description': 'Fetch data from any external REST API endpoint on a schedule.',
        'description_ko': '임의의 외부 REST API를 주기적으로 호출해 응답을 AI 지식으로 '
                          '주입합니다. JSON 응답에서 dot 표기법(JSON Path)으로 원하는 값만 '
                          '추출할 수 있습니다.',
        'usage': 'Endpoint URL과 인증 방식(필요 시)을 입력하고 활성화하세요. '
                 'JSON Path 예: data.value',
        'source_type': 'rest_api',
        'is_system': False,
    },
    'document': {
        'label': 'Document',
        'description': 'Upload a PDF, text, or markdown file and convert it to AI knowledge.',
        'description_ko': '서버에 있는 PDF/텍스트/마크다운 문서를 읽어 AI 지식으로 '
                          '변환합니다. 문서는 청크로 분할·요약(digest)되어 검색 색인에 '
                          '올라가며, AI가 [Library] 태그로 인용합니다.',
        'usage': '서버 내 파일 경로를 입력하고 활성화하세요. 문서 내용이 바뀌면 다음 '
                 '동기화 때 변경된 부분만 다시 처리됩니다.',
        'source_type': 'document',
        'is_system': False,
    },
    'web_url': {
        'label': 'Web URL',
        'description': 'Scrape a web page periodically and create context records from the content.',
        'description_ko': '웹 페이지를 주기적으로 수집해 본문을 AI 지식으로 변환합니다. '
                          'CSS 선택자를 지정하면 페이지에서 원하는 부분만 추출합니다.',
        'usage': '대상 URL을 입력하고 활성화하세요. 특정 영역만 필요하면 CSS 선택자를 '
                 '함께 지정하세요 (예: .data-table td).',
        'source_type': 'web_url',
        'is_system': False,
    },
    'internal_query': {
        'label': 'Internal Query',
        'description': 'Run a read-only DB query against the system and inject the result as context.',
        'description_ko': 'AoT 내부 데이터베이스에 읽기 전용 SQL 쿼리를 실행해 결과를 AI '
                          '지식으로 주입합니다. 고급 사용자용입니다.',
        'usage': 'SELECT 쿼리 템플릿을 입력하고 활성화하세요. 파라미터는 :이름 '
                 '플레이스홀더를 사용합니다.',
        'source_type': 'internal_query',
        'is_system': False,
    },
    'google_drive': {
        'label': 'Google Drive',
        'description': 'Pick one or more files from your Google Drive and convert them to AI knowledge.',
        'description_ko': "Google Drive에서 파일을 선택해 AI 지식으로 변환합니다. PDF·텍스트·"
                          '마크다운 파일은 그대로, Google 문서/프레젠테이션은 텍스트로, Google '
                          '스프레드시트는 첫 시트를 CSV로 변환해 등록합니다. 사용자 문서이므로 '
                          '[Library] 태그로 인용됩니다. 별도 API 키가 필요 없고, Settings > '
                          'Integrations에서 연결한 본인 Google 계정 권한을 그대로 사용합니다.',
        'usage': '먼저 Settings > Integrations에서 Google 계정을 연결하세요(연결되어 있지 '
                 '않으면 아래 버튼이 연결 화면으로 안내합니다). 이후 Google Drive에서 파일 '
                 '선택으로 파일을 고르고 활성화하세요. 문서 내용이 바뀌면 다음 동기화 때 '
                 '다시 가져옵니다.',
        'source_type': 'google_drive',
        'is_system': False,
    },
}


@ai_library_bp.route('/ai/library', methods=['GET'])
@login_required
def page_ai_library():
    """AI Library page — manage external knowledge sources.

    The library is a flat, farm-wide catalog: sources are not scoped to a
    site/facility. Which knowledge applies where is the AI's job at query
    time (keyword relevance in knowledge_search), not a property of the
    stored source.

    Excludes the reserved 'ai_curated' source (knowledge_shelve_service's
    _get_or_create_ai_curated_source — every AI-shelved note's FK target,
    never manually synced/activated) from this list. It exists so
    AIKnowledgeChunk.source_id always has somewhere to point; showing it here
    with an "Activate"/"Sync" control that does nothing meaningful would just
    confuse the operator. AI-curated knowledge has its own review section
    below instead.
    """
    sources = AIContextSource.query.filter(
        AIContextSource.is_active.is_(True),
        AIContextSource.source_type != 'ai_curated',
    ).order_by(AIContextSource.created_at.desc()).all()
    from aot.ai.context.ext.smartfarmkorea_client import (
        OPERATIONS as smartfarmkorea_operations,
        OUTDOOR_OPERATIONS as smartfarmkorea_outdoor_operations,
        LIVESTOCK_OPERATIONS as smartfarmkorea_livestock_operations,
    )
    return render_template(
        'pages/ai/ai_library.html',
        sources=sources,
        active_page='ai_library',
        library_presets=LIBRARY_PRESETS,
        review_items=knowledge_promotion_service.list_review_items(),
        smartfarmkorea_operations=smartfarmkorea_operations,
        smartfarmkorea_outdoor_operations=smartfarmkorea_outdoor_operations,
        smartfarmkorea_livestock_operations=smartfarmkorea_livestock_operations,
    )


# ---------------------------------------------------------------------------
# API: List sources
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/sources', methods=['GET'])
@login_required
def api_list_sources():
    """List all active AIContextSource entries (farm-wide, unscoped).

    Excludes the reserved 'ai_curated' source — see page_ai_library()."""
    sources = AIContextSource.query.filter(
        AIContextSource.is_active.is_(True),
        AIContextSource.source_type != 'ai_curated',
    ).order_by(AIContextSource.created_at.desc()).all()

    return jsonify({
        'success': True,
        'sources': [_source_to_dict(s) for s in sources],
    })


# ---------------------------------------------------------------------------
# API: Quick-add source (agent-style: immediate add, configure via cog)
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/sources/quick-add', methods=['POST'])
@login_required
def api_quick_add_source():
    """Immediately create a source entry from a preset key with auto-generated defaults.

    Body: { preset_key: str }
    Returns: { success: bool, source: dict }

    The user configures the source details afterwards via the settings cog.
    facility_id is not client-selectable: it's stamped from _resolve_facility_id()
    so synced AIContextRecord rows stay aligned with the Misc.default_facility_id
    chain their consumers (AI portal, context metadata builder) query by.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    body = request.get_json(silent=True) or {}
    preset_key = body.get('preset_key', '').strip()
    facility_id = _resolve_facility_id()

    preset = LIBRARY_PRESETS.get(preset_key)
    if not preset:
        return jsonify({'success': False, 'error': f'Unknown preset: {preset_key}'}), 400

    import uuid as _uuid
    short_id = str(_uuid.uuid4())[:8]
    source_name = preset['label']
    source_type = preset['source_type']
    parameter_name = f"{preset_key}.{short_id}"
    sync_interval_min = preset.get('sync_interval_min', 60)
    config_json = json.dumps({'preset_key': preset_key})

    try:
        source = AIContextSource(
            facility_id=facility_id,
            source_name=source_name,
            source_type=source_type,
            parameter_name=parameter_name,
            config_json=config_json,
            sync_interval_min=sync_interval_min,
            is_active=True,
            is_enabled=False,
        )
        db.session.add(source)
        db.session.commit()
        return jsonify({'success': True, 'source': _source_to_dict(source)}), 201

    except Exception as exc:
        logger.exception("api_quick_add_source failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# API: Create source
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/sources', methods=['POST'])
@login_required
def api_create_source():
    """Create a new AIContextSource from JSON body."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    body = request.get_json(silent=True) or {}
    facility_id = _resolve_facility_id()
    source_name = body.get('source_name', '').strip()
    source_type = body.get('source_type', '')
    parameter_name = body.get('parameter_name', '').strip()
    config_json = body.get('config_json', {})
    sync_interval_min = int(body.get('sync_interval_min', 60))

    if not source_name or not source_type or not parameter_name:
        return jsonify({'success': False, 'error': 'source_name, source_type, parameter_name are required'}), 400

    valid_types = {'rest_api', 'document', 'web_url', 'internal_query', 'google_drive'}
    if source_type not in valid_types:
        return jsonify({'success': False, 'error': f'Invalid source_type. Must be one of: {valid_types}'}), 400

    try:
        source = AIContextSource(
            facility_id=facility_id,
            source_name=source_name,
            source_type=source_type,
            parameter_name=parameter_name,
            config_json=json.dumps(config_json) if isinstance(config_json, dict) else config_json,
            sync_interval_min=sync_interval_min,
            is_active=True,
            is_enabled=False,
        )
        db.session.add(source)
        db.session.commit()
        return jsonify({'success': True, 'source': _source_to_dict(source)}), 201

    except Exception as exc:
        logger.exception("api_create_source failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# API: Update source
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/sources/<source_id>', methods=['PATCH'])
@login_required
def api_update_source(source_id):
    """Update fields on an existing AIContextSource."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    source = AIContextSource.query.filter_by(source_id=source_id).first()
    if not source:
        return jsonify({'success': False, 'error': 'Source not found'}), 404

    body = request.get_json(silent=True) or {}
    updatable = ['source_name', 'parameter_name', 'sync_interval_min', 'config_json']
    for field in updatable:
        if field in body:
            val = body[field]
            if field == 'config_json' and isinstance(val, dict):
                val = json.dumps(val)
            setattr(source, field, val)

    try:
        db.session.commit()
        return jsonify({'success': True, 'source': _source_to_dict(source)})
    except Exception as exc:
        logger.exception("api_update_source failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# API: Delete source
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/sources/<source_id>', methods=['DELETE'])
@login_required
def api_delete_source(source_id):
    """Soft-delete (deactivate) an AIContextSource."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    source = AIContextSource.query.filter_by(source_id=source_id).first()
    if not source:
        return jsonify({'success': False, 'error': 'Source not found'}), 404

    try:
        source.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'message': f'Source {source_id} deactivated.'})
    except Exception as exc:
        logger.exception("api_delete_source failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# API: Activate / Deactivate source
# ---------------------------------------------------------------------------

# Required config_json field per source_type, checked before activation.
_REQUIRED_CONFIG_FIELD = {
    'rest_api': ('endpoint_url', 'Endpoint URL'),
    'document': ('file_path', 'File Path'),
    'web_url': ('url', 'URL'),
    'internal_query': ('query_template', 'Query Template'),
}


def _missing_config_error(source):
    """Return an error message if source.config_json is missing a required
    field for its type, else None. Mirrors the required-field checks in
    context_source_service's fetch handlers, applied earlier so activation
    fails fast with a clear message instead of silently syncing nothing."""
    try:
        config = json.loads(source.config_json or '{}')
    except (ValueError, TypeError):
        config = {}

    preset_key = config.get('preset_key', '')
    preset = LIBRARY_PRESETS.get(preset_key)
    if preset and preset.get('is_system'):
        if not (config.get('api_key') or '').strip():
            return f"{preset.get('auth_key_name', 'API Key')} is required before activation."
        if preset.get('multi_operation'):
            operations = config.get('operations') or []
            if not operations:
                return 'Select at least one operation before activation.'
            from aot.ai.context.ext.smartfarmkorea_client import operations_for_preset
            _SFK_OPS = operations_for_preset(preset_key)
            for op_key in operations:
                op = _SFK_OPS.get(op_key)
                if not op:
                    continue
                missing = [p for p in op['params'] if p != 'serviceKey' and not (config.get(p) or '').strip()]
                if missing:
                    return f"{op['label_ko']}: {', '.join(missing)} is required before activation."
        return None

    if source.source_type == 'google_drive':
        # Not a single string field (see _REQUIRED_CONFIG_FIELD below) — needs
        # BOTH a connected Google account and at least one picked file.
        if not config.get('connected_user_id'):
            return 'Connect a Google account and pick at least one file before activation.'
        if not (config.get('files') or []):
            return 'Pick at least one file from Google Drive before activation.'
        return None

    field = _REQUIRED_CONFIG_FIELD.get(source.source_type)
    if field and not (config.get(field[0]) or '').strip():
        return f"{field[1]} is required before activation."
    return None


@ai_library_bp.route('/api/v1/ai/library/sources/<source_id>/activate', methods=['POST'])
@login_required
def api_activate_source(source_id):
    """Set is_enabled=True on an AIContextSource."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    source = AIContextSource.query.filter_by(source_id=source_id).first()
    if not source:
        return jsonify({'success': False, 'error': 'Source not found'}), 404

    missing_error = _missing_config_error(source)
    if missing_error:
        return jsonify({'success': False, 'error': missing_error}), 400

    try:
        source.is_enabled = True
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        logger.exception("api_activate_source failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


@ai_library_bp.route('/api/v1/ai/library/sources/<source_id>/deactivate', methods=['POST'])
@login_required
def api_deactivate_source(source_id):
    """Set is_enabled=False on an AIContextSource."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    source = AIContextSource.query.filter_by(source_id=source_id).first()
    if not source:
        return jsonify({'success': False, 'error': 'Source not found'}), 404

    try:
        source.is_enabled = False
        db.session.commit()
        return jsonify({'success': True})
    except Exception as exc:
        logger.exception("api_deactivate_source failed")
        db.session.rollback()
        return jsonify({'success': False, 'error': str(exc)}), 500


# ---------------------------------------------------------------------------
# API: Sync source
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/sources/<source_id>/sync', methods=['POST'])
@login_required
def api_sync_source(source_id):
    """Trigger an immediate sync for a single AIContextSource."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403

    source = AIContextSource.query.filter_by(source_id=source_id).first()
    if not source:
        return jsonify({'success': False, 'error': 'Source not found'}), 404

    if not source.is_enabled:
        return jsonify({
            'success': False,
            'error': 'Source is not enabled. Activate it before syncing.',
        }), 400

    messages = sync_source(source_id)
    has_error = bool(messages.get('error'))
    return jsonify({
        'success': not has_error,
        'messages': messages,
        'records_written': messages.get('records_written', 0),
    }), (200 if not has_error else 500)


# ---------------------------------------------------------------------------
# API: SmartFarmKorea discovery (Phase 1) — cascading-picker backend
#
# Turns the API's relational drill-down (identity → cropping → codes) into
# human-readable option lists so the settings modal's farm/season pickers
# never make the operator eyeball a 2,300-row dump and hand-copy a
# userId/croppingSerlNo. The same client-side resolve_farms/resolve_seasons
# primitive is what the Phase 2 AI setup tools will call. Only
# facility/outdoor presets have a discovery chain; livestock returns a clear
# "no discovery" error (its ops need only a date range).
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/smartfarmkorea/farms', methods=['POST'])
@login_required
def api_smartfarmkorea_farms():
    """Resolve the farm list for a dataset from a service key (calls the
    dataset's identity op). Body: { preset_key, api_key }.
    Returns { success, farms: [{value,label,userId,facilityId,itemCode}] }."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    body = request.get_json(silent=True) or {}
    preset_key = (body.get('preset_key') or '').strip()
    api_key = (body.get('api_key') or '').strip()
    if not api_key:
        return jsonify({'success': False, 'error': 'API key is required.'}), 400

    from aot.ai.context.ext.smartfarmkorea_client import operations_for_preset, resolve_farms
    farms, err = resolve_farms(api_key, operations=operations_for_preset(preset_key))
    if err:
        return jsonify({'success': False, 'error': err}), 502
    return jsonify({'success': True, 'farms': farms})


@ai_library_bp.route('/api/v1/ai/library/smartfarmkorea/seasons', methods=['POST'])
@login_required
def api_smartfarmkorea_seasons():
    """Resolve the season list for one farm (calls the dataset's cropping op).
    Body: { preset_key, api_key, user_id }.
    Returns { success, seasons: [{value,label,croppingSerlNo,itemCode}] }."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    body = request.get_json(silent=True) or {}
    preset_key = (body.get('preset_key') or '').strip()
    api_key = (body.get('api_key') or '').strip()
    user_id = (body.get('user_id') or '').strip()
    if not api_key:
        return jsonify({'success': False, 'error': 'API key is required.'}), 400
    if not user_id:
        return jsonify({'success': False, 'error': 'Select a farm first.'}), 400

    from aot.ai.context.ext.smartfarmkorea_client import operations_for_preset, resolve_seasons
    seasons, err = resolve_seasons(api_key, user_id, operations=operations_for_preset(preset_key))
    if err:
        return jsonify({'success': False, 'error': err}), 502
    return jsonify({'success': True, 'seasons': seasons})


# ---------------------------------------------------------------------------
# API: Google Drive picker config — everything the settings modal's "Pick
# from Google Drive" button needs to launch the Google Picker JS widget for
# the CURRENT user. No separate credential to configure per-source: it reuses
# the Google account already connected under Settings > Integrations
# (Calendar sync's UserCalendarConnection) plus one instance-wide Picker API
# key (Misc.google_picker_api_key — a client-side key, not the OAuth secret;
# see aot/utils/google_drive_api.py module docstring).
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/google-drive/picker-config', methods=['GET'])
@login_required
def api_google_drive_picker_config():
    """Returns what the Picker widget needs to launch for THIS user:
    { success, developer_key, connected, needs_rescope, account_email,
      oauth_token, connect_url }. `oauth_token`/`account_email` are only
      present when connected=true; the frontend shows a "connect your
      Google account" prompt (linking to connect_url) otherwise.

    needs_rescope=true is the important extra case: a connection made
    BEFORE drive.file was added to SCOPES (aot/utils/google_oauth.py) still
    refreshes access_tokens fine — Google honors the old, narrower scope
    forever — but every Drive API call on that token 403s
    (PERMISSION_DENIED), confirmed live 2026-07-21. There is no way to
    silently add a scope to an existing grant; the user must click through
    consent again (connect_url triggers prompt=consent, which re-asks for
    the CURRENT full SCOPES list). Reported as connected=false so the
    frontend's single "not connected" branch also catches this — the
    distinct flag is for a clearer message, not different UI structure.
    """
    from aot.utils import google_oauth
    from flask import url_for

    misc = Misc.query.first()
    developer_key = (getattr(misc, 'google_picker_api_key', '') or '').strip() if misc else ''

    result = {
        'success': True,
        'developer_key': developer_key,
        'picker_configured': bool(developer_key) and google_oauth.is_configured(),
        'connected': False,
        'needs_rescope': False,
        'account_email': None,
        'oauth_token': None,
        'connect_url': url_for('routes_integrations.oauth_google_start'),
    }

    from aot.databases.models.calendar_integration import UserCalendarConnection
    connection = (UserCalendarConnection.query
                  .filter_by(user_id=current_user.id, provider='google', is_active=True).first())
    if connection and connection.get_refresh_token():
        has_drive_scope = 'drive.file' in (connection.scope or '')
        if not has_drive_scope:
            result['needs_rescope'] = True
            result['account_email'] = connection.account_email
            return jsonify(result)
        from aot.ai.services.calendar_sync_service import get_valid_access_token
        token = get_valid_access_token(connection)
        if token:
            result['connected'] = True
            result['account_email'] = connection.account_email
            result['oauth_token'] = token
            result['user_id'] = current_user.id  # stored as config.connected_user_id on save
    return jsonify(result)


# ---------------------------------------------------------------------------
# API: AI-curated knowledge review (P5, docs/design/ai-library-redesign.md §8)
#
# The AI writes low-trust ai_curated notes on its own (knowledge_shelve, P4).
# These routes are the human half of §3.2's trust pipeline: confirm/edit
# promote to user_confirmed, retire excludes a note from search (row kept).
# Same edit_settings gate as source management — reviewing AI-written
# knowledge is an admin action, not a public one.
# ---------------------------------------------------------------------------

@ai_library_bp.route('/api/v1/ai/library/review', methods=['GET'])
@login_required
def api_list_review_items():
    """List ai_curated knowledge items for review, each with an advisory
    authoritative_match badge (see knowledge_promotion_service docstring for
    why that's advisory, not an auto-promotion signal)."""
    return jsonify({
        'success': True,
        'items': knowledge_promotion_service.list_review_items(),
    })


@ai_library_bp.route('/api/v1/ai/library/review/<chunk_id>/confirm', methods=['POST'])
@login_required
def api_confirm_review_item(chunk_id):
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    result = knowledge_promotion_service.confirm_item(chunk_id)
    return jsonify(result), (200 if result.get('success') else 404)


@ai_library_bp.route('/api/v1/ai/library/review/<chunk_id>/edit', methods=['POST'])
@login_required
def api_edit_review_item(chunk_id):
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    body = request.get_json(silent=True) or {}
    result = knowledge_promotion_service.edit_item(
        chunk_id,
        content=body.get('content'),
        heading=body.get('heading'),
        tags=body.get('tags'),
    )
    status = 200 if result.get('success') else (400 if 'tags' in (result.get('error') or '') else 404)
    return jsonify(result), status


@ai_library_bp.route('/api/v1/ai/library/review/<chunk_id>/retire', methods=['POST'])
@login_required
def api_retire_review_item(chunk_id):
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    result = knowledge_promotion_service.retire_item(chunk_id)
    return jsonify(result), (200 if result.get('success') else 404)


@ai_library_bp.route('/api/v1/ai/library/review/<chunk_id>/reactivate', methods=['POST'])
@login_required
def api_reactivate_review_item(chunk_id):
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    result = knowledge_promotion_service.reactivate_item(chunk_id)
    return jsonify(result), (200 if result.get('success') else 404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_facility_id():
    """Resolve facility_id from request args or Misc settings."""
    fid = request.args.get('facility_id', None)
    if not fid:
        misc = Misc.query.first()
        if misc and hasattr(misc, 'default_facility_id'):
            fid = misc.default_facility_id
    return fid or 'default'


def _source_to_dict(source):
    """Serialize AIContextSource to a JSON-safe dict."""
    return {
        'source_id': source.source_id,
        'facility_id': source.facility_id,
        'source_name': source.source_name,
        'source_type': source.source_type,
        'parameter_name': source.parameter_name,
        'config_json': source.config_json,
        'sync_interval_min': source.sync_interval_min,
        'last_synced_at': source.last_synced_at.isoformat() if source.last_synced_at else None,
        'last_sync_status': source.last_sync_status,
        'is_active': source.is_active,
        'is_enabled': bool(source.is_enabled),
        'created_at': source.created_at.isoformat() if source.created_at else None,
    }
