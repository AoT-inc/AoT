# coding=utf-8
"""사용자 지정 문자열(장치명·구역명·작물명 등)의 실시간 번역.

gettext 카탈로그는 소스에 박힌 문구만 덮는다. 사용자가 직접 지은 이름은 DB
원문 그대로 모든 언어에서 노출되어, 다국어 계정으로 열면 한 화면에 두 언어가
섞인다. 이 서비스는 그 이름들을 대상 언어로 번역해 캐시한다.

원칙 — 원문이 정본이다. 이 모듈은 원본 컬럼을 읽기만 하며, 번역본이 DB 의
`Input.name` 등으로 되써지는 경로는 존재하지 않는다. 캐시가 비어 있거나 엔진이
없으면 조용히 원문이 표시된다.

설계: docs/design/user-string-live-translation.md
"""
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta

from aot.aot_flask.extensions import db
from aot.databases.models.user_string_translation import (
    STATUS_DONE, STATUS_FAILED, STATUS_PENDING, STATUS_SKIPPED,
    UserStringTranslation)

logger = logging.getLogger(__name__)

# 번역 대상 최소/최대 길이. 1자짜리는 오탐 위험만 크고 얻는 게 없다.
MIN_LENGTH = 2
MAX_LENGTH = 200

# 한 번의 LLM 호출에 묶는 문자열 개수.
#
# 크게 잡을수록 호출이 줄지만, 응답이 모델의 출력 한도에서 잘리면 그 묶음이
# 통째로 버려진다(개수가 안 맞는 응답은 신뢰할 수 없으므로). 실측: gemini-2.5-flash
# 기본 설정에서 40개는 11번째 항목에서 잘렸다. 20 으로 잡고, 그래도 잘리면
# `translate_rows()` 가 절반씩 쪼개 다시 시도한다 — 모델과 한도가 무엇이든
# 결국 번역되도록.
BATCH_SIZE = 20

# 이 횟수만큼 연속 실패하면 더 시도하지 않는다.
MAX_FAIL_COUNT = 3

_TRANSLATIONS_DIR = None
_CATALOG_CACHE = {}


# ---------------------------------------------------------------------------
# 정규화 · 해시 · 언어 감지
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r'\s+')

# 번역하면 안 되는 식별자 꼴. 사람이 읽는 이름이 아니라 기계 식별자다.
_IDENTIFIER_RES = [
    re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'                # UUID
               r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'),
    re.compile(r'^[0-9a-fA-F]{16}$'),                            # DevEUI/AppEUI
    re.compile(r'^[0-9a-fA-F]{32}$'),                            # AppKey
    re.compile(r'^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$'),    # MAC
    re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$'),                    # IPv4
    re.compile(r'^[/~.]?/[\w./-]+$'),                            # 경로
    re.compile(r'^\w+://'),                                      # URL
    re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$'),                   # 이메일
]

# 숫자·기호·공백만으로 이루어진 문자열 — 번역할 내용이 없다.
_NO_LETTERS_RE = re.compile(r'^[\W\d_]+$', re.UNICODE)


def normalize(text):
    """조회 키로 쓸 정규화. 앞뒤 공백 제거 + 연속 공백 축약까지만 한다.

    대소문자와 문장부호는 건드리지 않는다 — 이름의 정체성이기 때문이다.
    """
    if not text:
        return ''
    return _WHITESPACE_RE.sub(' ', str(text)).strip()


def text_hash(text):
    """정규화된 원문의 sha1 앞 16자."""
    return hashlib.sha1(normalize(text).encode('utf-8')).hexdigest()[:16]


def detect_script_lang(text):
    """유니코드 스크립트로 원어를 1차 판정한다.

    라틴 문자처럼 여러 언어가 공유하는 스크립트는 판정하지 않고 'auto' 를
    돌려준다 — 엔진이 감지하게 두는 편이 틀린 단정보다 낫다.
    """
    counts = {}
    for ch in text:
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        script = name.split(' ')[0]
        counts[script] = counts.get(script, 0) + 1

    if not counts:
        return 'auto'

    dominant = max(counts, key=counts.get)
    return {
        'HANGUL': 'ko',
        'HIRAGANA': 'ja',
        'KATAKANA': 'ja',
        'CYRILLIC': 'ru',
        'THAI': 'th',
        'DEVANAGARI': 'hi',
        'ARABIC': 'ar',
        'HEBREW': 'he',
    }.get(dominant, 'auto')
    # CJK 는 의도적으로 뺐다 — 한자만으로는 zh/ja 를 가를 수 없다.


def is_structurally_translatable(text):
    """구조만 보고 번역 대상인지 판정한다(카탈로그 충돌은 별도).

    Returns:
        (bool, str) — 대상 여부와 아닐 경우의 사유.
    """
    norm = normalize(text)
    if not norm:
        return False, 'empty'
    if len(norm) < MIN_LENGTH:
        return False, 'too_short'
    if len(norm) > MAX_LENGTH:
        return False, 'too_long'
    if _NO_LETTERS_RE.match(norm):
        return False, 'no_letters'
    for pattern in _IDENTIFIER_RES:
        if pattern.match(norm):
            return False, 'identifier'
    return True, ''


# ---------------------------------------------------------------------------
# gettext 카탈로그 충돌 — 이중 번역 방지
# ---------------------------------------------------------------------------

def _translations_dir():
    global _TRANSLATIONS_DIR
    if _TRANSLATIONS_DIR is None:
        import os
        _TRANSLATIONS_DIR = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            'aot_flask', 'translations')
    return _TRANSLATIONS_DIR


def catalog_terms(lang):
    """해당 로케일 gettext 카탈로그의 msgid·msgstr 집합.

    사용자가 출력 이름을 "Pump" 나 "온도"로 지었다면, 그 문자열을 사전에 넣는
    순간 같은 단어를 쓰는 시스템 문구까지 함께 바뀐다. 그런 키는 아예 사전에서
    빼야 한다.
    """
    if lang in _CATALOG_CACHE:
        return _CATALOG_CACHE[lang]

    terms = set()
    try:
        from babel.support import Translations
        translations = Translations.load(_translations_dir(), [lang])
        catalog = getattr(translations, '_catalog', {}) or {}
        for msgid, msgstr in catalog.items():
            if isinstance(msgid, str) and msgid:
                terms.add(normalize(msgid))
            if isinstance(msgstr, str) and msgstr:
                terms.add(normalize(msgstr))
    except Exception:
        logger.exception("catalog_terms: failed to load catalog for %s", lang)

    if not terms:
        # 영어는 원문이라 `translations/en` 자체가 없다. 그대로 두면 영어 화면
        # 에서는 이 가드가 통째로 꺼진다 — 사용자가 장치를 "Temperature" 라고
        # 지으면 그 시스템 문구까지 번역기가 건드릴 수 있다. msgid 는 어느
        # 로케일에서 읽어도 같은 영어 원문이므로, 아무 카탈로그에서나 그것만
        # 가져와 채운다.
        terms = _source_msgids()

    terms.discard('')
    _CATALOG_CACHE[lang] = terms
    return terms


_SOURCE_MSGIDS = None


def _source_msgids():
    """카탈로그의 msgid(영어 원문) 집합. 로케일과 무관하게 같다."""
    global _SOURCE_MSGIDS
    if _SOURCE_MSGIDS is not None:
        return set(_SOURCE_MSGIDS)

    ids = set()
    try:
        from babel.support import Translations
        for probe in ('ko', 'ja', 'de'):
            catalog = getattr(
                Translations.load(_translations_dir(), [probe]),
                '_catalog', {}) or {}
            if catalog:
                for msgid in catalog:
                    if isinstance(msgid, str) and msgid:
                        ids.add(normalize(msgid))
                break
    except Exception:
        logger.exception("_source_msgids: failed")

    _SOURCE_MSGIDS = ids
    return set(ids)


def collides_with_catalog(text, lang):
    """이 문자열이 UI 문구로도 쓰이는가."""
    return normalize(text) in catalog_terms(lang)


# ---------------------------------------------------------------------------
# 번역 대상 원문 수집
# ---------------------------------------------------------------------------

# (모델 경로, 필드명, 도메인). 여기 없는 필드는 번역되지 않는다.
#
# 의도적으로 뺀 것들 — 사람 이름(User.name), 자격증명 라벨(APIKey/UserAPIKey),
# 권한 식별자(Role.name), MCP 서버 이름. 번역하면 오히려 해가 된다.
SOURCE_SPECS = [
    ('Input', 'name', 'device'),
    ('Output', 'name', 'device'),
    ('InputChannel', 'name', 'measurement'),
    ('OutputChannel', 'name', 'measurement'),
    ('DeviceMeasurements', 'name', 'measurement'),
    ('PID', 'name', 'function'),
    ('Function', 'name', 'function'),
    ('Conditional', 'name', 'function'),
    ('Trigger', 'name', 'function'),
    ('Method', 'name', 'function'),
    ('Dashboard', 'name', 'dashboard'),
    ('Widget', 'name', 'dashboard'),
    ('Camera', 'name', 'device'),
    ('Tab', 'name', 'misc'),
    ('GeoMap', 'name', 'zone'),
    ('GeoLayer', 'name', 'zone'),
    ('GeoFacility', 'name', 'zone'),
    ('GeoModelAsset', 'name', 'zone'),
    ('GeoPlot', 'name', 'crop'),
    ('GeoPlot', 'subject', 'crop'),
    ('GeoPlot', 'variety', 'crop'),
    ('GeoProgram', 'name', 'program'),
    ('GeoProgram', 'subject', 'crop'),
    ('GeoProgram', 'variety', 'crop'),
    ('Notes', 'name', 'note_title'),
    ('NoteTags', 'name', 'misc'),
    ('NoticePost', 'title', 'notice'),
]


def _geoshape_names():
    """GeoShape 의 이름은 GeoJSON feature 안에 있어 별도로 꺼낸다.

    구역 이름은 화면에서 가장 자주 보이는 사용자 문자열이라 빼놓을 수 없다.
    """
    out = []
    try:
        from aot.databases.models import GeoShape
        for shape in GeoShape.query.with_entities(GeoShape.feature).all():
            feature = shape[0]
            if isinstance(feature, str):
                try:
                    feature = json.loads(feature)
                except (ValueError, TypeError):
                    continue
            if not isinstance(feature, dict):
                continue
            props = feature.get('properties') or {}
            if not isinstance(props, dict):
                continue
            for key in ('name', 'aot_name', 'label'):
                value = props.get(key)
                if isinstance(value, str) and value.strip():
                    out.append((value, 'zone'))
    except Exception:
        logger.exception("_geoshape_names: failed")
    return out


def _geoprogram_strings():
    """관리 프로그램의 이름들은 JSON 컬럼 안에 있어 별도로 꺼낸다.

    `stages[].name` — 단계 이름("육묘" "정식" "개화" "녹협"). 프로그램 화면에서
    가장 자주 보이는 문자열이고, 사용자가 작목에 맞춰 직접 짓는다.

    `target_defs[].label` — 목표 항목 이름. 기본 항목은 영어라 대개 gettext
    카탈로그와 충돌해 걸러지고, 사용자가 추가한 항목만 남는다.

    의도적으로 빼는 것:
      - `resource_defs[].role` — 'irrigation' 같은 역할 **식별자**다. 코드가
        이 값으로 함수를 찾으므로 번역하면 연결이 끊긴다.
      - `stages[].guidance`, `notes` — 문단 단위 지침이다. 이 번역기는 텍스트
        노드 전체가 사전 키와 정확히 같을 때만 치환하는데, 긴 문단은 줄바꿈·
        공백 처리로 일치가 쉽게 깨진다. 길이 상한에도 걸린다. 장문은 별도
        설계가 필요하다(설계 문서 P6).
    """
    out = []
    try:
        from aot.databases.models import GeoProgram
        rows = GeoProgram.query.with_entities(
            GeoProgram.stages, GeoProgram.target_defs).all()
    except Exception:
        logger.exception("_geoprogram_strings: query failed")
        return out

    def _as_list(value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                return []
        return value if isinstance(value, list) else []

    for stages, target_defs in rows:
        for stage in _as_list(stages):
            if isinstance(stage, dict):
                name = stage.get('name')
                if isinstance(name, str) and name.strip():
                    out.append((name, 'program'))
        for target in _as_list(target_defs):
            if isinstance(target, dict):
                label = target.get('label')
                if isinstance(label, str) and label.strip():
                    out.append((label, 'measurement'))
    return out


def collect_source_strings():
    """번역 대상 원문 전부를 모은다.

    Returns:
        dict — {정규화된 원문: 도메인}
    """
    from aot.databases import models

    collected = {}

    def add(value, domain):
        if not isinstance(value, str):
            return
        norm = normalize(value)
        if not norm:
            return
        # 먼저 등록된 도메인을 유지한다 — 같은 문자열이 여러 곳에 쓰여도
        # 번역은 하나여야 하고, 도메인은 프롬프트 힌트일 뿐이다.
        collected.setdefault(norm, domain)

    for model_name, field, domain in SOURCE_SPECS:
        model = getattr(models, model_name, None)
        if model is None:
            continue
        column = getattr(model, field, None)
        if column is None:
            continue
        try:
            for (value,) in model.query.with_entities(column).all():
                add(value, domain)
        except Exception:
            logger.exception("collect_source_strings: %s.%s failed",
                             model_name, field)

    for value, domain in _geoshape_names():
        add(value, domain)

    for value, domain in _geoprogram_strings():
        add(value, domain)

    return collected


# ---------------------------------------------------------------------------
# 설정 · 엔진
# ---------------------------------------------------------------------------

def _settings():
    try:
        from aot.databases.models import AIGlobalSettings
        return AIGlobalSettings.query.first()
    except Exception:
        return None


def is_enabled():
    """**표시** 스위치 — 사전에 있는 번역을 화면에 쓸 것인가.

    AI 를 보지 않는다. 번역본을 보여주는 데에는 LLM 이 필요 없기 때문이다.
    사람이 관리 화면에서 손으로 넣은 번역만으로도 이 기능은 성립한다 — AI 를
    쓰지 않는 설치가 적지 않고, 그런 곳에서도 자기가 쓰는 한두 언어는 직접
    채워 넣을 수 있어야 한다.

    (처음에는 이것을 `ai_enabled` 에 함께 걸었는데, 그러면 손으로 넣은 번역이
    저장은 되고 화면에는 안 나오는 상태가 된다 — 사용자에게는 고장으로 보인다.)
    """
    settings = _settings()
    if not settings:
        return False
    return bool(getattr(settings, 'user_string_translation_enabled', False))


def can_auto_translate():
    """**자동 번역** 스위치 — 엔진을 불러 새 번역을 만들 것인가.

    이쪽만 AI 를 요구한다. 꺼져 있으면 미번역 문자열은 큐에 남고, 관리 화면에서
    사람이 채울 때까지 원문이 표시된다.
    """
    if not is_enabled():
        return False
    settings = _settings()
    return bool(settings and getattr(settings, 'ai_enabled', False))


def _resolve_engine():
    """번역에 쓸 엔진. 특정 모델을 가정하지 않는다.

    설정에 지정된 에이전트를 우선하고, 없으면 활성 에이전트 중 가벼운 역할을
    고른다. 하나도 없으면 None — 호출부는 조용히 원문을 유지한다.
    """
    settings = _settings()
    if not settings:
        return None, None

    try:
        from aot.databases.models import AIAgent
        from aot.ai.services.ai_agent_service import AIAgentService
    except Exception:
        logger.exception("_resolve_engine: import failed")
        return None, None

    agent = None
    configured = getattr(settings, 'user_string_translation_agent_id', None)
    if configured:
        agent = AIAgent.query.filter_by(unique_id=configured,
                                        is_activated=True).first()
    if not agent:
        agent = (AIAgent.query.filter_by(pipeline_role='worker',
                                         is_activated=True).first() or
                 AIAgent.query.filter_by(is_activated=True).first())
    if not agent:
        return None, None

    try:
        engine = AIAgentService.get_engine(agent.unique_id)
    except Exception:
        logger.exception("_resolve_engine: get_engine failed for %s",
                         agent.unique_id)
        return None, None

    return engine, agent


# ---------------------------------------------------------------------------
# 조회 · 적재
# ---------------------------------------------------------------------------

def lookup(texts, target_lang):
    """캐시 조회 전용. LLM 을 부르지 않는다.

    요청 경로에서 쓰는 유일한 함수다 — 화면 렌더가 번역 지연에 묶이면 안 된다.

    Returns:
        dict — {원문: 번역본}. 미번역은 키 자체가 없다.
    """
    normed = {normalize(t) for t in texts if t}
    normed.discard('')
    if not normed:
        return {}

    hashes = [text_hash(t) for t in normed]
    out = {}
    # SQLite 의 변수 상한(999)을 넘지 않게 나눠 조회한다.
    for i in range(0, len(hashes), 500):
        chunk = hashes[i:i + 500]
        rows = UserStringTranslation.query.filter(
            UserStringTranslation.target_lang == target_lang,
            UserStringTranslation.status == STATUS_DONE,
            UserStringTranslation.source_hash.in_(chunk)).all()
        for row in rows:
            if row.translated_text:
                out[row.source_text] = row.translated_text
    return out


def enqueue(items, target_lang):
    """미번역 문자열을 pending 으로 적재한다.

    Args:
        items: {원문: 도메인} 또는 원문 이터러블.

    Returns:
        새로 적재된 개수.
    """
    if isinstance(items, dict):
        pairs = list(items.items())
    else:
        pairs = [(t, 'misc') for t in items]

    if not pairs:
        return 0

    existing = set()
    hashes = [text_hash(t) for t, _ in pairs]
    for i in range(0, len(hashes), 500):
        chunk = hashes[i:i + 500]
        rows = UserStringTranslation.query.with_entities(
            UserStringTranslation.source_hash).filter(
            UserStringTranslation.target_lang == target_lang,
            UserStringTranslation.source_hash.in_(chunk)).all()
        existing.update(r[0] for r in rows)

    catalog = catalog_terms(target_lang)
    added = 0
    for text, domain in pairs:
        norm = normalize(text)
        digest = text_hash(norm)
        if not norm or digest in existing:
            continue
        existing.add(digest)

        translatable, reason = is_structurally_translatable(norm)
        if translatable and norm in catalog:
            translatable, reason = False, 'catalog_collision'

        source_lang = detect_script_lang(norm)
        if translatable and source_lang != 'auto' and source_lang == target_lang:
            # 이미 대상 언어다 — 번역할 게 없다.
            translatable, reason = False, 'same_language'

        db.session.add(UserStringTranslation(
            source_hash=digest,
            source_text=norm,
            source_lang=source_lang,
            target_lang=target_lang,
            domain=domain or 'misc',
            status=STATUS_PENDING if translatable else STATUS_SKIPPED,
            translated_text=None,
            engine=None if translatable else reason,
        ))
        added += 1

    if added:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("enqueue: commit failed")
            return 0
    return added


def sync_sources(target_lang):
    """DB 의 사용자 문자열 전부를 훑어 미등록분을 적재한다.

    주기 잡에서 호출한다. 이름이 새로 생기거나 바뀌면 여기서 잡힌다.
    """
    sources = collect_source_strings()
    return enqueue(sources, target_lang)


# ---------------------------------------------------------------------------
# 번역 실행
# ---------------------------------------------------------------------------

_PROMPT = """You are translating short UI labels from a farm automation system.
These are names the operator wrote themselves — device names, zone names, crop
names, function names.

Translate each item into {target_name} ({target_lang}).

Rules:
- Keep proper nouns, brand names, model numbers, units and symbols as they are.
- These are screen labels: keep them short. Do not add explanations.
- Preserve any leading/trailing numbering the operator used.
- If an item is already in the target language, repeat it unchanged.
{glossary}
Respond with ONLY a JSON array of strings, exactly {count} items, in the same
order as the input. No prose, no markdown fence.

Input:
{payload}"""


def _glossary_block(domain):
    """도메인 용어집. 작물명처럼 정답 표가 있는 것은 흔들리지 않게 한다."""
    lines = []
    try:
        from aot.databases.models import AIDomainGlossary
        terms = AIDomainGlossary.query.filter_by(is_active=True).limit(40).all()
        for term in terms:
            if term.term and term.definition:
                lines.append(f"  {term.term}: {term.definition}")
    except Exception:
        pass

    if not lines:
        return ''
    return ("- Domain glossary (use these meanings):\n" +
            "\n".join(lines) + "\n")


def _parse_response(raw, expected_count):
    """엔진 응답에서 JSON 배열을 꺼낸다. 실패하면 None."""
    if not raw:
        return None
    text = str(raw).strip()

    # ```json ... ``` 울타리를 벗긴다.
    fence = re.search(r'```(?:json)?\s*(.+?)\s*```', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    start = text.find('[')
    end = text.rfind(']')
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None

    if not isinstance(parsed, list) or len(parsed) != expected_count:
        return None
    if not all(isinstance(item, str) for item in parsed):
        return None
    return parsed


def _daily_used():
    """오늘 번역한 건수."""
    since = datetime.utcnow() - timedelta(days=1)
    try:
        return UserStringTranslation.query.filter(
            UserStringTranslation.status == STATUS_DONE,
            UserStringTranslation.updated_at >= since).count()
    except Exception:
        return 0


def _daily_limit():
    settings = _settings()
    if not settings:
        return 0
    return int(getattr(settings, 'user_string_translation_daily_limit', 500) or 500)


def translate_rows(rows):
    """pending 행 묶음을 실제로 번역해 저장한다.

    Returns:
        번역에 성공한 개수.
    """
    if not rows:
        return 0

    engine, agent = _resolve_engine()
    if not engine:
        logger.debug("translate_rows: no engine available — leaving pending")
        return 0

    from aot.config import LANGUAGES

    target_lang = rows[0].target_lang
    target_name = LANGUAGES.get(target_lang, target_lang)
    domain = rows[0].domain
    payload = json.dumps([r.source_text for r in rows], ensure_ascii=False,
                         indent=None)

    prompt = _PROMPT.format(
        target_name=target_name,
        target_lang=target_lang,
        glossary=_glossary_block(domain),
        count=len(rows),
        payload=payload)

    try:
        result = engine.run_reasoning({}, prompt)
    except Exception:
        logger.exception("translate_rows: engine call failed")
        _mark_failed(rows)
        return 0

    raw = ''
    if isinstance(result, dict):
        raw = result.get('insight') or result.get('response') or ''
    else:
        raw = result

    parsed = _parse_response(raw, len(rows))
    if parsed is None:
        # 묶음이 크면 응답이 출력 한도에서 잘려 개수가 안 맞는다. 절반씩 쪼개
        # 다시 시도한다 — 모델마다 한도가 다르고, 우리는 그 값을 모른다.
        # 한 건까지 내려가서도 실패하면 그때 실패로 기록한다.
        if len(rows) > 1:
            mid = len(rows) // 2
            logger.info("translate_rows: response unusable for %d items "
                        "(lang=%s) — splitting", len(rows), target_lang)
            return (translate_rows(rows[:mid]) + translate_rows(rows[mid:]))

        logger.warning("translate_rows: unparseable response for %r (lang=%s)",
                       rows[0].source_text, target_lang)
        _mark_failed(rows)
        return 0

    engine_label = None
    if agent is not None:
        engine_label = f"{getattr(agent, 'model_name', '') or ''}"[:120] or None

    done = 0
    for row, translated in zip(rows, parsed):
        value = normalize(translated)
        if not value:
            row.status = STATUS_FAILED
            row.fail_count = (row.fail_count or 0) + 1
            continue
        row.translated_text = value
        row.status = STATUS_DONE
        row.fail_count = 0
        row.engine = engine_label
        done += 1

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("translate_rows: commit failed")
        return 0

    return done


def _mark_failed(rows):
    for row in rows:
        row.fail_count = (row.fail_count or 0) + 1
        row.status = (STATUS_SKIPPED if row.fail_count >= MAX_FAIL_COUNT
                      else STATUS_FAILED)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def run_batch(target_lang=None, limit=BATCH_SIZE):
    """pending 을 배치로 번역한다. 주기 잡의 진입점.

    Returns:
        dict — {'translated': n, 'remaining': n, 'reason': str|None}
    """
    if not can_auto_translate():
        # 표시만 켜져 있고 AI 가 없는 설치. 큐는 그대로 두어, 관리 화면에서
        # 사람이 채우거나 나중에 AI 를 붙였을 때 이어서 처리되게 한다.
        return {'translated': 0, 'remaining': 0, 'reason': 'no_engine'}

    used = _daily_used()
    cap = _daily_limit()
    if used >= cap:
        return {'translated': 0, 'remaining': 0, 'reason': 'daily_limit'}

    limit = min(limit, cap - used)

    query = UserStringTranslation.query.filter(
        UserStringTranslation.status.in_([STATUS_PENDING, STATUS_FAILED]),
        UserStringTranslation.fail_count < MAX_FAIL_COUNT)
    if target_lang:
        query = query.filter(UserStringTranslation.target_lang == target_lang)

    # 같은 (언어, 도메인) 끼리 묶어야 프롬프트 하나로 처리된다.
    rows = query.order_by(UserStringTranslation.target_lang,
                          UserStringTranslation.domain,
                          UserStringTranslation.id).limit(limit).all()
    if not rows:
        return {'translated': 0, 'remaining': 0, 'reason': None}

    groups = {}
    for row in rows:
        groups.setdefault((row.target_lang, row.domain), []).append(row)

    translated = 0
    for group in groups.values():
        translated += translate_rows(group)

    remaining = query.count()
    return {'translated': translated, 'remaining': remaining, 'reason': None}


def translate_now(texts, target_lang, domain='misc', max_items=BATCH_SIZE):
    """화면에 실제로 보이는 문자열을 즉시 번역한다.

    브라우저가 사전에 없는 문자열을 만났을 때 부르는 경로다. 캐시 히트는 바로
    돌려주고, 미스는 상한 안에서 동기 번역한다. 상한을 넘는 나머지는 pending
    으로 남아 주기 잡이 처리한다.

    Returns:
        dict — {'entries': {원문: 번역본}, 'pending': [원문...]}
    """
    normed = [normalize(t) for t in texts if t]
    normed = [t for t in normed if t]
    if not normed:
        return {'entries': {}, 'pending': []}

    if not is_enabled():
        return {'entries': {}, 'pending': []}

    # 캐시 조회는 AI 와 무관하다 — 사람이 넣은 번역도 여기서 나온다.
    hits = lookup(normed, target_lang)
    misses = [t for t in normed if t not in hits]
    if not misses:
        return {'entries': hits, 'pending': []}

    # 미번역은 엔진이 없어도 적재한다. 그래야 관리 화면의 목록에 올라와
    # 사람이 채울 수 있다.
    enqueue({t: domain for t in misses}, target_lang)

    if not can_auto_translate():
        return {'entries': hits, 'pending': misses}

    used = _daily_used()
    cap = _daily_limit()
    budget = max(0, min(max_items, cap - used))

    if budget:
        hashes = [text_hash(t) for t in misses]
        rows = UserStringTranslation.query.filter(
            UserStringTranslation.target_lang == target_lang,
            UserStringTranslation.status.in_([STATUS_PENDING, STATUS_FAILED]),
            UserStringTranslation.fail_count < MAX_FAIL_COUNT,
            UserStringTranslation.source_hash.in_(hashes[:500])
        ).limit(budget).all()

        groups = {}
        for row in rows:
            groups.setdefault(row.domain, []).append(row)
        for group in groups.values():
            translate_rows(group)

        hits = lookup(normed, target_lang)

    pending = [t for t in normed if t not in hits]
    return {'entries': hits, 'pending': pending}


# ---------------------------------------------------------------------------
# 역방향 — 번역된 이름으로 부른 것을 원문으로 되돌린다
# ---------------------------------------------------------------------------

def reverse_lookup(text, target_lang=None):
    """번역본을 원문으로 되돌린다. 사전에 없으면 None.

    일본어 화면을 보는 사용자가 "1号ハウスの温度は?" 라고 물으면, AI 의 이름
    리졸버는 DB 의 "1번 하우스" 를 찾지 못한다. 화면에 보이는 이름과 저장된
    이름이 다르기 때문이다. 번역 사전을 별칭 인덱스로 되읽어 그 간극을 잇는다.

    Args:
        target_lang: 지정하면 그 언어의 번역만 본다. None 이면 모든 언어.
    """
    norm = normalize(text)
    if not norm:
        return None

    try:
        query = UserStringTranslation.query.filter(
            UserStringTranslation.status == STATUS_DONE,
            UserStringTranslation.translated_text == norm)
        if target_lang:
            query = query.filter(
                UserStringTranslation.target_lang == target_lang)
        row = query.first()
    except Exception:
        return None

    if not row or row.source_text == norm:
        return None
    return row.source_text


# ---------------------------------------------------------------------------
# 사전 (브라우저로 내려보내는 형태)
# ---------------------------------------------------------------------------

def build_catalog(target_lang):
    """브라우저에 내려줄 번역 사전.

    Returns:
        dict — {'entries': {원문: 번역본}, 'pending': [원문...]}

    `pending` 은 "번역 대상이지만 아직 번역본이 없는" 원문이다. 브라우저는 이
    목록에 있는 문자열을 화면에서 실제로 만났을 때만 서버에 번역을 요청한다 —
    보이지도 않는 이름을 미리 번역하느라 호출을 쓰지 않기 위해서다.
    """
    rows = UserStringTranslation.query.filter(
        UserStringTranslation.target_lang == target_lang,
        UserStringTranslation.status.in_([STATUS_DONE, STATUS_PENDING,
                                          STATUS_FAILED])).all()

    entries = {}
    pending = []
    for row in rows:
        if row.status == STATUS_DONE and row.translated_text:
            if row.translated_text != row.source_text:
                entries[row.source_text] = row.translated_text
        elif row.fail_count < MAX_FAIL_COUNT:
            pending.append(row.source_text)

    return {'entries': entries, 'pending': pending}


def catalog_fingerprint(target_lang):
    """사전 캐시 무효화용 지문.

    번역이 하나라도 추가·변경되면 값이 바뀐다.

    모든 페이지 렌더에서 도는 경로라 짧게 캐시한다. 사전 응답 자체가
    max-age=300 이므로 60초 지연은 체감되지 않는다.
    """
    cache_key = f"user_i18n_fp:{target_lang}"
    try:
        from aot.aot_flask.extensions import cache
        cached = cache.get(cache_key)
        if cached:
            return cached
    except Exception:
        cache = None

    try:
        row = db.session.query(
            db.func.count(UserStringTranslation.id),
            db.func.max(UserStringTranslation.updated_at)
        ).filter(UserStringTranslation.target_lang == target_lang).first()
        count, latest = row if row else (0, None)
        stamp = latest.isoformat() if latest else '0'
        fingerprint = hashlib.sha1(
            f"{count}:{stamp}".encode('utf-8')).hexdigest()[:12]
    except Exception:
        logger.exception("catalog_fingerprint failed")
        return '0'

    try:
        from aot.aot_flask.extensions import cache
        cache.set(cache_key, fingerprint, timeout=60)
    except Exception:
        pass
    return fingerprint
