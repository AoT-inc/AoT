# coding=utf-8
"""
KnowledgeSearch — v3.1 tier architecture, Phase 5 (agentic knowledge search).

Realizes the architecture proposal §12-5: agentic search FIRST, embedding as a
later fallback. AoT already had two doc-access paths, but neither is agentic
search over the markdown corpus:
  - read_manual reads a WHOLE doc (or one section) but requires the AI to
    already know the filename AND the exact section heading (navigate the
    title index first) — the "통짜 로드 / 사전 탐색" the proposal warns against.
  - AiDocService.search only covers the structured JSON catalogues
    (functions/outputs/inputs), not the markdown docs.

This tool lets the AI express a NEED as a free query ("VPD 계산", "관수 스케줄
설정") and get the most relevant SECTION CONTENTS across ALL markdown docs —
no prior knowledge of file/heading, no whole-doc load, no embedding index.
Markdown is the source of truth (MD가 정본, §6-1); the HTML portal is human-only.

Deterministic keyword/section scoring — no LLM, no tokens, no vector DB. The
embedding fallback for natural-language-similar queries where keywords fail is
a deliberate later add (§12-5), not built here.

@phase active
@stability new
@dependency docs/*.md (markdown corpus)
"""
import logging
import os
import re
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_HEADER = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
_HANGUL = re.compile(r'[가-힣]')

# 띄어쓰기로 낱말을 가르지 않는 문자 — **한글은 여기 없다.** 한국어는 띄어쓰기를
# 쓰므로 `_tokenize` 가 이미 낱말을 받고 어간(앞 2글자)만 더하면 됐다. 아래
# 문자들은 사정이 다르다: 문장 전체가 공백 없이 이어져 들어와 토큰이 **하나**가
# 되고, 그 하나가 Latin 취급을 받아 `\b` 단어경계 정규식으로 매칭되니 사실상
# 아무것도 찾지 못한다.
#
# 실측(2026-08-22) — AoT 는 22개 언어로 출시되는데 그중 넷이 이 상태였다:
#   한국어 5토큰 · English 5 · Nederlands 3 · हिन्दी 8 · Русский 6  (정상)
#   日本語 1 · 中文 1 · 繁體中文 1 · ไทย 1                          (검색 불가)
# 일본어 자료를 올린 사용자는 **아무 에러 없이 0건**을 받는다. 라이브러리가 비어
# 있다는 안내조차 뜨지 않는다 — 자료는 실제로 있기 때문이다.
#
# 가르는 근거가 없으므로 표준적인 방법을 쓴다: **문자 bigram**(인접 두 글자).
# 형태소 분석기를 들이지 않는 이유는 언어마다 다른 사전과 무게가 붙기 때문이고,
# bigram 은 사전 없이 어느 문자에나 같은 규칙으로 선다.
_NO_WORD_BREAK = re.compile(
    '['
    '぀-ゟ'   # 히라가나
    '゠-ヿ'   # 가타카나
    'ㇰ-ㇿ'   # 가타카나 확장
    '㐀-䶿'   # CJK 확장 A
    '一-鿿'   # CJK 통합 한자 (中文·漢字)
    '豈-﫿'   # CJK 호환 한자
    '฀-๿'   # 태국어
    ']'
)

# bigram 은 글자 수만큼 늘어나므로 긴 질문에서 토큰이 폭주할 수 있다. 점수는
# **한 질문 안에서의 순위**에만 쓰이므로(절대 임계값이 없다) 상한을 둬도 판정이
# 흔들리지 않는다.
_MAX_QUERY_TOKENS = 64


def _splits_on_spaces(token):
    """이 토큰을 부분문자열로 맞춰야 하는가 → bool.

    한글과 위 `_NO_WORD_BREAK` 문자들이 여기 해당한다. Latin·키릴·데바나가리는
    낱말 경계가 있으므로 `\\b` 매칭이 맞다('how' ⊄ 'however')."""
    return bool(_HANGUL.search(token) or _NO_WORD_BREAK.search(token))

# Localized translation variants (About.de.md, index.ja.md, …) add noise without
# adding distinct content. Index the base/Korean/English and skip other locales.
_KEEP_LOCALES = ('.ko', '.md')  # <name>.ko.md and <name>.md
_LOCALE_SUFFIX = re.compile(r'\.[a-z]{2}\.md$')

# Internal engineering / design docs live in docs/ too, but they are NOT the user
# manual — indexing them pollutes capability/how-to answers (observed: a "how to
# add a sensor" query matched i18n_translation_guide.md). Exclude by explicit
# name and by this repo's internal-doc naming conventions (ALL_CAPS_UNDERSCORE,
# design_/directive_ prefixes, _design/_Analysis suffixes, PLAN- prefix).
_EXCLUDE_DOCS = frozenset({
    'AoT_Architecture_Analysis.md',
    'TASK_ORCHESTRATION_IMPLEMENTATION.md',
    'PLAN-IEC-WIDGET.md',
    'design_facility_3d_preview.md',
    'directive_phase1_facility_3d.md',
    'env_control_enhancement_design.md',
    'i18n_translation_guide.md',
    'Dependencies.md',
})
_INTERNAL_DOC_RE = re.compile(
    r'(^[A-Z0-9]+(_[A-Z0-9]+)+\.md$)'      # TASK_ORCHESTRATION_IMPLEMENTATION.md
    r'|(^(design|directive)_)'              # design_*.md / directive_*.md
    r'|(_design\.md$)|(_Analysis\.md$)'     # *_design.md / *_Analysis.md
    r'|(^PLAN-)'                            # PLAN-*.md
)

# Generic English words that carry no topical signal — they substring-match almost
# any section and drown the real query terms. (Korean particles are handled by
# stemming in _tokenize instead.)
_STOPWORDS = frozenset({
    'how', 'what', 'where', 'when', 'why', 'who', 'which',
    'the', 'a', 'an', 'to', 'of', 'for', 'in', 'on', 'at', 'by', 'is', 'are',
    'do', 'does', 'did', 'can', 'could', 'would', 'should', 'will', 'i', 'you',
    'my', 'me', 'it', 'this', 'that', 'and', 'or', 'with', 'about', 'from',
    'please', 'want', 'need', 'like', 'get', 'have', 'be',
})

# Domain vocabulary bridge: a user's everyday word for a feature ('센서') is not
# the word the manual/filenames use ('입력', 'input'). Without this, '센서 추가'
# never reaches Inputs.md. Each query token here is EXPANDED with its aliases
# (added as extra scoring tokens, incl. the English doc/filename term so the
# filename boost fires). Keep small and high-precision — this is navigation
# vocabulary, not synonyms in general.
_QUERY_ALIASES = {
    '센서': ('입력', 'input'),
    '입력': ('input',),
    '측정': ('입력', 'input'),
    '출력': ('output',),
    '액추에이터': ('출력', 'output'),
    '밸브': ('출력', 'output'),
    '펌프': ('출력', 'output'),
    '위젯': ('widget', 'dashboard', '대시보드'),
    '대시보드': ('dashboard', 'widget'),
    '색': ('테마', '색상', 'color', 'theme', 'ui'),
    '색상': ('테마', 'color', 'theme', 'ui'),
    '테마': ('색상', 'color', 'theme'),
    '함수': ('function',),
    '자동화': ('function', '함수'),
    '지도': ('geo', 'map'),
    '알림': ('alert', 'alerts'),
    '카메라': ('camera',),
    '백업': ('backup', 'restore', 'export'),
    '보정': ('calibration',),
}

# Module-level lazy cache of the section index. Built once, cheap to hold.
_sections = None  # list of dicts
_index_lock = threading.Lock()

# Library-knowledge cache (Phase 6 knowledge digest). Unlike the markdown
# index above (static per process — docs don't change at runtime), library
# chunks change whenever an operator syncs an AI Library source, so this is
# re-fetched whenever max(updated_at) moves — a cheap query, not a full
# rebuild, and it's a no-op entirely when the feature flag is off.
# See .local/plans/phase6_knowledge_digest_design.md.
_library_sections = []
_library_stamp = None
_library_lock = threading.Lock()


def _docs_dir():
    from aot.config import INSTALL_DIRECTORY
    return os.path.join(INSTALL_DIRECTORY, 'docs')


def _is_indexable(filename):
    if not filename.endswith('.md'):
        return False
    m = _LOCALE_SUFFIX.search(filename)
    if m and not filename.endswith('.ko.md'):
        return False  # skip non-Korean locale variants
    if filename in _EXCLUDE_DOCS or _INTERNAL_DOC_RE.search(filename):
        return False  # skip internal engineering / design docs (not the manual)
    return True


def _split_sections(filename, text):
    """Split one markdown doc into (heading, level, content) sections."""
    sections = []
    lines = text.splitlines()
    cur_heading, cur_level, buf = None, 0, []

    def flush():
        if cur_heading is not None or buf:
            sections.append({
                'file': filename,
                'heading': cur_heading or '(intro)',
                'level': cur_level,
                'content': '\n'.join(buf).strip(),
            })

    for line in lines:
        m = _HEADER.match(line)
        if m:
            flush()
            cur_level = len(m.group(1))
            cur_heading = m.group(2).strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return [s for s in sections if s['content'] or s['heading'] != '(intro)']


def _build_index():
    global _sections
    with _index_lock:
        if _sections is not None:
            return _sections
        out = []
        try:
            docs = _docs_dir()
            for fn in sorted(os.listdir(docs)):
                if not _is_indexable(fn):
                    continue
                try:
                    with open(os.path.join(docs, fn), 'r', encoding='utf-8') as f:
                        out.extend(_split_sections(fn, f.read()))
                except Exception as e:
                    logger.debug(f"[KnowledgeSearch] skip {fn}: {e}")
        except Exception as e:
            logger.warning(f"[KnowledgeSearch] index build failed: {e}")
        _sections = out
        logger.info(f"[KnowledgeSearch] indexed {len(out)} sections from markdown docs.")
        return _sections


def reset_index():
    """Drop the cached index (e.g. after docs change). Next search rebuilds."""
    global _sections
    with _index_lock:
        _sections = None


# @ANCHOR: LOAD_LIBRARY_SECTIONS
def _load_library_sections():
    """Fetch AIKnowledgeChunk rows as index entries (same shape as a markdown
    section, plus 'origin': 'library' and the P1 unified-item fields —
    provenance/trust_state/attribution/content_kind/tags/entity_ref, see
    docs/design/ai-library-redesign.md §2). Returns [] immediately (no DB
    touch) when knowledge_digest_enabled is off — the manual-only search
    stays exactly as it was pre-Phase-6. Re-fetches only when max(updated_at)
    changed since the last call, so a steady-state search pays one cheap
    scalar query, not a full row fetch.

    ttl is deliberately NOT filtered here: this list is process-cached and an
    item's expiry doesn't bump updated_at, so a stale cache could keep an
    expired row past its ttl. search() re-checks ttl against "now" on every
    call instead."""
    global _library_sections, _library_stamp
    try:
        from aot.databases.models import AIGlobalSettings, AIKnowledgeChunk
        settings = AIGlobalSettings.query.first()
        if not (settings and getattr(settings, 'knowledge_digest_enabled', False)):
            return []

        from aot.aot_flask.extensions import db as _db
        from sqlalchemy import func
        stamp = _db.session.query(func.max(AIKnowledgeChunk.updated_at)).scalar()
        stamp_key = stamp.isoformat() if stamp else None

        with _library_lock:
            if stamp_key == _library_stamp and _library_sections:
                return _library_sections

            confirmed_only = bool(getattr(settings, 'knowledge_chunk_confirmed_only', False))
            q = AIKnowledgeChunk.query.filter_by(is_enabled=True)
            if confirmed_only:
                # P6 redefinition (design §9): this used to require
                # context_state=='user_confirmed' on EVERY row, which — before
                # P5's review UI existed — meant turning this on made all
                # library knowledge vanish with no way to ever get it back.
                # Now it only suppresses ai_curated notes nobody has reviewed
                # yet; external_authority/user_provided/data_derived rows
                # (and ai_curated rows that ARE confirmed/corroborated) are
                # unaffected — this flag is "hide unreviewed AI notes", not
                # "hide everything but hand-confirmed rows".
                q = q.filter(
                    (AIKnowledgeChunk.provenance != 'ai_curated')
                    | (AIKnowledgeChunk.context_state != 'system_generated')
                )

            out = []
            for row in q.all():
                out.append({
                    'file': row.source_name or '지식',
                    'heading': row.section_title or '(요약)',
                    'level': 2,
                    'content': row.digest_text or '',
                    'keywords': (row.keywords or '').lower(),
                    'origin': 'library',
                    'provenance': row.provenance or 'user_provided',
                    'trust_state': row.context_state or 'system_generated',
                    'attribution': row.attribution or row.source_name or '',
                    'content_kind': row.content_kind or 'prose',
                    'tags': [t.strip().lower() for t in (row.tags or '').split(',') if t.strip()],
                    'entity_ref': row.entity_ref,
                    'ttl': row.ttl,
                    # P5 (knowledge_promotion_service.note_reuse) needs the row
                    # id to bump reuse_count on a hit — None for ext-authority
                    # sections (not AIKnowledgeChunk rows, no promotion path).
                    'chunk_id': row.unique_id,
                })
            _library_sections = out
            _library_stamp = stamp_key
            logger.info(f"[KnowledgeSearch] loaded {len(out)} library knowledge chunk(s).")
            return _library_sections
    except Exception as e:
        logger.warning(f"[KnowledgeSearch] library chunk load failed: {e}")
        return []


# @ANCHOR: LOAD_SEMANTIC_NOTE_SECTIONS
def _load_semantic_note_sections():
    """P6 (docs/design/ai-library-redesign.md §5 decision #2): AoT already had
    a 'confirmed knowledge/decisions' path — Notes rows with
    category='ai_semantic' (the same set ai_context_service.
    get_global_decisions surfaces for a DIFFERENT context slot). Decision #2
    was search-layer integration ONLY: Notes' own storage/UX/model is
    untouched (no unification with AIKnowledgeChunk) — this just makes those
    notes ALSO candidates for knowledge_search, tagged provenance=
    'user_provided' (a human wrote and confirmed it — same trust tier as a
    registered document, see §3.1).

    Deliberately NOT process-cached like _load_library_sections /
    _load_external_authority_sections: Notes has no reliable "last modified"
    column to key a cache stamp on (date_time is creation time), and
    ai_semantic notes are a small, low-churn set (confirmed decisions, not
    routine per-device notes) — a fresh query per search() call is cheap
    enough that a wrong-by-construction cache would cost more than it saves."""
    try:
        from aot.databases.models import Notes
        notes = Notes.query.filter_by(category='ai_semantic', is_archived=False).all()
        out = []
        for n in notes:
            if not n.note:
                continue
            tag_list = [t.strip() for t in (n.tags or '').split(',') if t.strip()]
            # Same exclusion get_global_decisions applies — a note the user
            # marked wrong/stale isn't confirmed knowledge anymore.
            if any(t.lower() in ('incorrect', 'obsolete', 'error') for t in tag_list):
                continue
            out.append({
                'file': '노트',
                'heading': n.name or n.note[:40],
                'level': 2,
                'content': n.note,
                'keywords': ' '.join(tag_list).lower(),
                'origin': 'library',
                'provenance': 'user_provided',
                'trust_state': n.context_state or 'system_generated',
                'attribution': f'노트 ({n.date_time.date()})' if n.date_time else '노트',
                'content_kind': 'prose',
                'tags': [t.lower() for t in tag_list],
                'entity_ref': n.target_id,
                'ttl': None,
                'chunk_id': None,  # not an AIKnowledgeChunk row — no reuse-promotion path
            })
        return out
    except Exception as e:
        logger.warning(f"[KnowledgeSearch] semantic note load failed: {e}")
        return []


def _normalize_tags(tags):
    """Accept a list[str] or comma-separated str (or None) and return a set of
    lowercase, stripped tag tokens. Empty input -> empty set (no tag filter)."""
    if not tags:
        return set()
    if isinstance(tags, str):
        tags = tags.split(',')
    return {t.strip().lower() for t in tags if t and t.strip()}


def _naive_utc(dt):
    """Strip tzinfo if present. ExtPestAlerts.fetched_at is written as
    tz-aware (datetime.now(timezone.utc)); everything else in this module
    compares against datetime.utcnow() (naive) — mixing the two raises
    TypeError, so every external timestamp is normalized to naive UTC here
    before use."""
    if dt is not None and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


# Ext-authority cache (P3, docs/design/ai-library-redesign.md §7/§10). Same
# process-cache pattern as _load_library_sections: these tables only change
# on a scheduled sync (minutes-to-days interval, see AIContextSource.
# sync_interval_min for EXT-KR-01/02/03), so a per-call query would be pure
# waste. Deliberately NOT reusing ExtSmartfarmClient.get_setpoints() — that
# method triggers a network refetch on a stale/empty cache (side effect
# unsafe on a search-time read path); this queries the cache tables directly
# and leaves the fetch/refresh machinery (scheduler-driven) untouched.
_ext_authority_sections = []
_ext_authority_stamp = None
_ext_authority_lock = threading.Lock()


def _format_smartfarm_row(row):
    """One ext_smartfarm_setpoints row -> one structured content block, e.g.
    '온도 18–26°C · 습도 60–80% · CO2 400–800ppm · 광 200–400µmol/m²/s' — the
    fix for the pre-P3 bridge that shredded this same row into 8 separate
    flat AIContextRecord strings (docs/design/ai-library-redesign.md §7)."""
    parts = []
    if row.opt_temp_min is not None or row.opt_temp_max is not None:
        parts.append(f"온도 {row.opt_temp_min}–{row.opt_temp_max}°C")
    if row.opt_humidity_min is not None or row.opt_humidity_max is not None:
        parts.append(f"습도 {row.opt_humidity_min}–{row.opt_humidity_max}%")
    if row.opt_co2_min is not None or row.opt_co2_max is not None:
        parts.append(f"CO2 {row.opt_co2_min}–{row.opt_co2_max}ppm")
    if row.opt_light_min is not None or row.opt_light_max is not None:
        parts.append(f"광 {row.opt_light_min}–{row.opt_light_max}µmol/m²/s")
    return ' · '.join(parts)


def _load_external_authority_sections():
    """Fetch RDA SmartFarm / Nongsaro / NCPMS ext_* cache rows as index
    entries — same dict shape as _load_library_sections() (origin, tags,
    provenance, ttl, ...) so search()'s tag/ttl filtering and
    search_as_text()'s provenance tagging apply to both uniformly. Re-fetches
    only when max(fetched_at) across the three tables moves."""
    global _ext_authority_sections, _ext_authority_stamp
    try:
        from aot.databases.models import ExtSmartfarmSetpoints, ExtNongsaroGuides, ExtPestAlerts
        from aot.aot_flask.extensions import db as _db
        from sqlalchemy import func

        stamps = []
        for model in (ExtSmartfarmSetpoints, ExtNongsaroGuides, ExtPestAlerts):
            s = _db.session.query(func.max(model.fetched_at)).scalar()
            if s:
                stamps.append(_naive_utc(s))
        stamp_key = max(stamps).isoformat() if stamps else None

        with _ext_authority_lock:
            if stamp_key == _ext_authority_stamp and _ext_authority_sections:
                return _ext_authority_sections
            if not stamp_key:
                _ext_authority_sections, _ext_authority_stamp = [], None
                return []

            out = []
            for row in ExtSmartfarmSetpoints.query.all():
                content = _format_smartfarm_row(row)
                if not content:
                    continue
                out.append({
                    'file': 'RDA SmartFarm (EXT-KR-01)',
                    'heading': f'{row.crop_type} · {row.growth_stage} 최적 설정값',
                    'level': 2,
                    'content': content,
                    'keywords': f'{row.crop_type} {row.growth_stage}'.lower(),
                    'origin': 'library',
                    'provenance': 'external_authority',
                    'trust_state': 'corroborated',
                    'attribution': f'RDA SmartFarm API, 갱신 {_naive_utc(row.fetched_at).date()}',
                    'content_kind': 'structured',
                    'tags': [row.crop_type.lower(), row.growth_stage.lower()],
                    'entity_ref': None,
                    'ttl': None,  # agronomic constants — not time-sensitive like an alert
                })

            for row in ExtNongsaroGuides.query.all():
                content = '\n'.join(p for p in (row.title, row.content) if p)
                if not content:
                    continue
                out.append({
                    'file': 'Nongsaro (EXT-KR-02)',
                    'heading': row.title or f'{row.crop_type} · {row.guide_type} 가이드',
                    'level': 2,
                    'content': content,
                    'keywords': f'{row.crop_type} {row.guide_type}'.lower(),
                    'origin': 'library',
                    'provenance': 'external_authority',
                    'trust_state': 'corroborated',
                    'attribution': 'Nongsaro Open API (농사로)',
                    'content_kind': 'prose',
                    'tags': [row.crop_type.lower(), row.guide_type.lower()],
                    'entity_ref': None,
                    'ttl': None,
                })

            for row in ExtPestAlerts.query.all():
                content = (
                    f"심각도: {row.severity or '정보없음'} · 지역: {row.region or '전국'}\n"
                    f"방제법: {row.control_method or '정보없음'}"
                )
                fetched = _naive_utc(row.fetched_at)
                out.append({
                    'file': 'NCPMS (EXT-KR-03)',
                    'heading': f'{row.crop_type} 병해충 경보 — {row.pest_name or row.pest_code}',
                    'level': 2,
                    'content': content,
                    'keywords': f'{row.crop_type} {row.pest_name or ""} 병해충'.lower(),
                    'origin': 'library',
                    'provenance': 'external_authority',
                    'trust_state': 'corroborated',
                    'attribution': '국가병해충관리시스템 (NCPMS)',
                    'content_kind': 'prose',
                    'tags': [row.crop_type.lower(), 'pest', row.pest_code.lower()],
                    'entity_ref': None,
                    # Pest alerts are time-sensitive (013_DATA_SOURCES.yaml: 6h TTL)
                    # — an outdated alert injected as ground truth is worse than
                    # none, so this is the one ext feed that actually expires.
                    'ttl': fetched + timedelta(hours=6) if fetched else None,
                })

            _ext_authority_sections = out
            _ext_authority_stamp = stamp_key
            logger.info(f"[KnowledgeSearch] loaded {len(out)} ext-authority section(s).")
            return _ext_authority_sections
    except Exception as e:
        logger.warning(f"[KnowledgeSearch] ext-authority load failed: {e}")
        return []


def _tokenize(text):
    """Query → scoring tokens. Drops English stopwords (generic words that match
    everything), and for inflected Korean adds a 2-char stem prefix so '추가하는'
    / '등록하려면' still match the doc stem '추가' / '등록' (Korean is
    agglutinative; the doc rarely contains the exact inflected form)."""
    raw = [t for t in re.split(r'[\s,./()\[\]{}:;"\'`|?!~]+', (text or '').lower()) if len(t) >= 2]
    out = []
    for t in raw:
        is_hangul = bool(_HANGUL.search(t))
        # 띄어쓰기가 없는 문자(일본어·중국어·태국어 등)는 문장 전체가 토큰
        # 하나로 들어온다 — `_NO_WORD_BREAK` 주석 참조. **한글은 여기 해당하지
        # 않는다**(띄어쓰기를 쓰므로 아래 어간 경로가 그대로 맞다).
        unsegmented = bool(_NO_WORD_BREAK.search(t))
        if not (is_hangul or unsegmented) and t in _STOPWORDS:
            continue
        if t not in out:
            out.append(t)
        if unsegmented:
            # 자를 근거가 없으니 인접 두 글자로 훑는다. 통째 토큰도 위에서
            # 이미 넣었으므로, 원문에 그 문장이 그대로 있으면 더 높게 잡힌다.
            for i in range(len(t) - 1):
                if len(out) >= _MAX_QUERY_TOKENS:
                    break
                bg = t[i:i + 2]
                if bg not in out:
                    out.append(bg)
            stem = t[:2]
        else:
            stem = t[:2] if (is_hangul and len(t) >= 3) else t
            if stem not in out:
                out.append(stem)
        # Domain-vocabulary bridge: expand the token (or its Korean stem) with
        # navigation aliases so '센서' also scores against 입력 / input / Inputs.md.
        for alias in _QUERY_ALIASES.get(t, ()) + _QUERY_ALIASES.get(stem, ()):
            if alias not in out:
                out.append(alias)
    return out


def search(query, top_k=3, max_chars=1400, tags=None):
    """Return the top-k markdown/library sections most relevant to `query`,
    each as {file, heading, score, content, origin, provenance, trust_state,
    attribution, content_kind, tags} with content truncated to max_chars.

    Scoring (deterministic): heading matches weigh 3×, content matches 1×; both
    substring-based so partial Korean tokens match. Empty when no query or no
    section scores > 0.

    Library knowledge (AIKnowledgeChunk) is indexed farm-wide alongside the
    always-global markdown manual: the AI Library is a flat catalog, not
    site-scoped. Which knowledge applies to which site/zone/crop is decided
    here by keyword relevance at query time, not by a stored facility filter
    (the former facility_id gate was removed with the AI Library's site
    picker — a per-source site assignment can't track what's actually grown
    where, and open-field farms had no facility rows to scope by at all).
    Registered external-authority feeds (RDA SmartFarm/Nongsaro/NCPMS ext_*
    cache tables, P3) are candidates the same way — see
    _load_external_authority_sections(). Confirmed semantic Notes
    (category='ai_semantic', P6 §5 decision #2) are candidates too, tagged
    provenance='user_provided' — see _load_semantic_note_sections(). Notes
    storage/UX itself is untouched; this is search-layer integration only.

    `tags` (list[str] or comma-separated str, optional) narrows library
    candidates to items whose own tags intersect the given set — the
    domain-agnostic replacement for the old facility_id axis (crop, livestock,
    a named structure, whatever the caller's context resolves to). Omitting
    it preserves the current farm-wide default (no narrowing) so existing
    callers are unaffected. An untagged library item (tags=[]) is always a
    candidate regardless of the filter, same as the always-global manual —
    it hasn't been scoped by anyone yet, so it isn't excluded by a scope it
    doesn't claim. Expired items (ttl in the past) are excluded here rather
    than at cache-load time, since ttl expiry doesn't invalidate the cache."""
    if not query or not query.strip():
        return []
    req_tags = _normalize_tags(tags)
    lib_sections = (
        _load_library_sections()
        + _load_external_authority_sections()
        + _load_semantic_note_sections()
    )
    if req_tags:
        lib_sections = [
            s for s in lib_sections
            if not s.get('tags') or (req_tags & set(s['tags']))
        ]
    now = datetime.utcnow()
    lib_sections = [s for s in lib_sections if not s.get('ttl') or s['ttl'] > now]
    sections = _build_index() + lib_sections
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    scored = []
    for s in sections:
        heading_l = s['heading'].lower()
        content_l = s['content'].lower()
        kw_l = s.get('keywords', '')
        # Filename as a topical signal: 'Inputs.md' / 'Supported-Inputs.md' should
        # rank for an 'input' query even when the body is in another language.
        # Library entries' 'file' is a source name, not a filename — don't
        # strip a trailing 3 chars off it.
        fname_raw = s['file'][:-3] if s['file'].endswith('.md') else s['file']
        fname_l = fname_raw.replace('-', ' ').replace('_', ' ').lower()
        score = 0
        for tok in q_tokens:
            if _splits_on_spaces(tok):
                # 낱말 경계가 없는 문자 — 부분문자열로 맞춘다. 한글뿐 아니라
                # 일본어·중국어·태국어도 여기다(예전에는 한글만 이 갈래로 와서,
                # 나머지는 `\b` 로 매칭돼 영영 못 찾았다).
                if tok in heading_l:
                    score += 3
                if tok in content_l:
                    score += 1
                if tok in fname_l:
                    score += 2
                if kw_l and tok in kw_l:
                    score += 2
            else:
                # Latin token: word-boundary match so 'how'⊄'however', 'add'⊄'address'.
                pat = r'\b' + re.escape(tok) + r'\b'
                if re.search(pat, heading_l):
                    score += 3
                if re.search(pat, content_l):
                    score += 1
                if re.search(pat, fname_l):
                    score += 2
                if kw_l and re.search(pat, kw_l):
                    score += 2
        if score > 0:
            scored.append((score, s))

    scored.sort(key=lambda x: (-x[0], len(x[1]['content'])))
    results = []
    reuse_candidate_ids = []
    for score, s in scored[:top_k]:
        content = s['content']
        if len(content) > max_chars:
            content = content[:max_chars] + '\n... [truncated]'
        origin = s.get('origin', 'manual')
        results.append({
            'file': s['file'],
            'heading': s['heading'],
            'score': score,
            'content': content,
            'origin': origin,
            # Manual sections have no provenance/trust concept — they're the
            # software's own documentation, not a knowledge item — so these
            # are only meaningful when origin == 'library'.
            'provenance': s.get('provenance') if origin == 'library' else None,
            'trust_state': s.get('trust_state') if origin == 'library' else None,
            'attribution': s.get('attribution') if origin == 'library' else None,
            'content_kind': s.get('content_kind') if origin == 'library' else None,
            'tags': s.get('tags', []) if origin == 'library' else [],
        })
        # P5: an ai_curated hit surfacing here is a "reuse" — see
        # knowledge_promotion_service.note_reuse for why this is a cheap raw
        # UPDATE, not a cache-busting ORM write.
        if origin == 'library' and s.get('provenance') == 'ai_curated' and s.get('chunk_id'):
            reuse_candidate_ids.append(s['chunk_id'])

    if reuse_candidate_ids:
        try:
            from aot.ai.services.knowledge_promotion_service import note_reuse
            note_reuse(reuse_candidate_ids)
        except Exception as e:
            logger.debug(f"[KnowledgeSearch] note_reuse skipped: {e}")

    return results


# Provenance -> the citation tag shown in the injected block, per
# docs/design/ai-library-redesign.md §6. The model is told (via
# _MANUAL_GROUNDING_DIRECTIVE in ai_agent_service.py) to cite these
# differently — an ai_curated note is the AI's own past unconfirmed summary,
# not something it should present with the same authority as a real source.
_PROVENANCE_TAG = {
    'external_authority': '[권위]',
    'user_provided': '[Library]',
    'data_derived': '[관측]',
}

# ai_curated's tag depends on trust_state too, NOT just provenance (P5) — a
# human confirming a note (knowledge_promotion_service.confirm_item/edit_item)
# or it auto-corroborating via reuse (note_reuse) changes context_state but
# NOT provenance (provenance is WHERE it came from, permanent; context_state
# is HOW MUCH it's trusted, mutable). Keying the tag on provenance alone was
# a real bug: a confirmed item would cite as "미확인" (unconfirmed) forever.
_AI_CURATED_TRUST_TAG = {
    'system_generated': '[AI 정리 — 미확인]',
    'user_confirmed': '[AI 정리 — 확인됨]',
    'corroborated': '[AI 정리 — 교차검증됨]',
}


def _format_hit_tag(hit):
    """Citation prefix for one search() hit. Manual (origin == 'manual') has
    no provenance concept — it's the software's own docs — so it gets no tag,
    same as before P1."""
    if hit.get('origin') != 'library':
        return ''
    provenance = hit.get('provenance')
    if provenance == 'ai_curated':
        tag = _AI_CURATED_TRUST_TAG.get(hit.get('trust_state'), '[AI 정리 — 미확인]')
    else:
        tag = _PROVENANCE_TAG.get(provenance, '[Library]')
    return f"{tag} "


def library_is_populated():
    """도메인 지식 라이브러리에 **읽을 것이 하나라도 있는가** → bool.

    빈 결과의 원인을 가르기 위한 것이다. `search()` 는 저장소에 늘 있는 매뉴얼
    (`_build_index()`)과 동기화된 라이브러리 청크를 함께 뒤지므로, 결과가 비었을
    때 그것이 "검색어가 안 맞았다" 인지 "애초에 자료가 없다" 인지 호출자가 알 수
    없다. 자료가 없는 설치에서 "다른 키워드로 해 보라" 고 답하면 모델은 키워드만
    바꿔 가며 같은 빈손을 반복하고, 끝내 라이브러리가 비었다는 사실을 모른 채
    자기 지식으로 넘어간다 — 그리고 그것을 출처처럼 적는다.

    여기서 보는 것은 **청크뿐**이다(매뉴얼은 제외). 매뉴얼은 AoT 사용법이라
    작물·가축 같은 도메인 질문에는 원래 답하지 못하고, 그것까지 세면 어떤
    설치에서도 "비어 있다" 가 나오지 않아 판정이 무의미해진다.

    실패는 조용히 True 로 돌린다 — 판정하지 못했을 때 "비었다" 고 단정하면
    자료가 있는 설치에서 없는 안내를 하게 된다. 모르면 평소 문구가 낫다.
    """
    try:
        from aot.databases.models import AIGlobalSettings, AIKnowledgeChunk
        settings = AIGlobalSettings.query.first()
        if not (settings and getattr(settings, 'knowledge_digest_enabled', False)):
            # 기능 자체가 꺼져 있으면 청크는 검색에 실리지 않는다
            # (`_load_library_sections` 가 곧바로 [] 를 돌려준다) — 사용자에게는
            # 자료가 없는 것과 같다.
            return False
        return AIKnowledgeChunk.query.filter_by(is_enabled=True).first() is not None
    except Exception:
        return True


def search_as_text(query, top_k=3, max_chars=1400, tags=None):
    """Search and format the result as a compact text block for injection into
    a tool result / reasoning context. Empty string when nothing matches.

    Each library hit is tagged by provenance (§6) so the model can tell an
    authoritative source from its own unconfirmed prior note apart — see
    _PROVENANCE_TAG and _MANUAL_GROUNDING_DIRECTIVE."""
    hits = search(query, top_k=top_k, max_chars=max_chars, tags=tags)
    if not hits:
        return ''
    blocks = []
    for h in hits:
        tag = _format_hit_tag(h)
        attribution = f" — {h['attribution']}" if h.get('attribution') else ''
        blocks.append(f"### {tag}{h['heading']}  ({h['file']}{attribution})\n{h['content']}")
    return f"[Knowledge search: '{query}' — {len(hits)} section(s)]\n\n" + "\n\n---\n\n".join(blocks)
