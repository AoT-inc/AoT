# coding=utf-8
"""
utils_ai_context_source.py — Sync utilities for AIContextSource.

Dispatches sync operations by source_type and writes results into AIContextRecord.
All functions return a messages dict: {"success": [], "info": [], "warning": [], "error": []}.
"""
import hashlib
import json
import logging
import pathlib
import re
from datetime import datetime

from bs4 import BeautifulSoup
from aot.aot_flask.extensions import db
from aot.databases.models import (
    AIContextSource, AIContextRecord, AILibrarySyncLog, AIKnowledgeChunk, AIGlobalSettings,
)

logger = logging.getLogger(__name__)

# @ANCHOR: EXT_CLIENT_MAP
# Maps preset_key → fully-qualified class path for ext system source clients.
# Used by _dispatch_ext_client() to dynamically load the correct client.
EXT_CLIENT_MAP = {
    'ext_smartfarm': 'aot.ai.context.ext.smartfarm_client.ExtSmartfarmClient',
    'ext_nongsaro':  'aot.ai.context.ext.nongsaro_client.NongsaroClient',
    'ext_pest':      'aot.ai.context.ext.pest_management_client.PestManagementClient',
}


# @ANCHOR: SYNC_SOURCE_DISPATCHER
def sync_source(source_id):
    """
    Load AIContextSource by source_id, dispatch to appropriate fetch handler,
    and persist results as AIContextRecord rows.

    Dispatch priority:
        1. If config_json contains a preset_key registered in EXT_CLIENT_MAP,
           route to the corresponding ext client via _dispatch_ext_client().
        2. Otherwise, dispatch by source_type (rest_api, document, web_url,
           internal_query) — unchanged behaviour.

    Returns a messages dict with keys:
        success, info, warning, error (list[str] each), records_written (int).
    """
    messages = {"success": [], "info": [], "warning": [], "error": [], "records_written": 0}
    source = None
    config = {}

    try:
        source = AIContextSource.query.filter_by(source_id=source_id, is_active=True).first()
        if not source:
            messages["error"].append(f"Source not found or inactive: {source_id}")
            return messages

        try:
            config = json.loads(source.config_json or '{}')
        except (ValueError, TypeError):
            messages["warning"].append("config_json is malformed — using empty config.")

        # Pre-check: route to ext client if preset_key is in EXT_CLIENT_MAP
        preset_key = config.get('preset_key', '')
        records = None
        err = None
        raw_payload = None

        if preset_key and preset_key in EXT_CLIENT_MAP:
            result = _dispatch_ext_client(source, config, preset_key)
            if isinstance(result, dict) and 'error' in result:
                err = result['error']
            else:
                records = result
                raw_payload = json.dumps(records)[:10000] if records else None
        elif preset_key in ('smartfarmkorea', 'smartfarmkorea_outdoor', 'smartfarmkorea_livestock'):
            # @ANCHOR: SMARTFARMKOREA_DIGEST
            # Multi-operation, operator-selected presets (EXT-KR-04 시설원예 /
            # EXT-KR-05 노지 / EXT-KR-06 축산) — unlike the EXT_CLIENT_MAP
            # presets above (each a single bounded reference table
            # shredded/cached uniformly), SmartFarmKorea's operations have
            # heterogeneous per-operation schemas with no shared shape, so
            # there's no single AIContextRecord parameter_name to shred into.
            # All three presets go straight to the SAME chunk+digest pipeline
            # a document/web_url source uses (records stays [] — no
            # AIContextRecord write at all for these presets, only
            # AIKnowledgeChunk rows). The outdoor/livestock presets just
            # select a different operations dict — same client, same digest
            # shape.
            from aot.ai.context.ext.smartfarmkorea_client import (
                fetch_and_format_selected, operations_for_preset,
            )
            sf_operations = operations_for_preset(preset_key)
            text, sf_tags, sf_errors = fetch_and_format_selected(config, operations=sf_operations)
            records = []
            if not text:
                err = '; '.join(sf_errors) if sf_errors else 'No operations selected, or all selected operations failed.'
            else:
                raw_payload = text[:10000]
                if sf_errors:
                    messages["warning"].extend(sf_errors)
                if _digest_enabled():
                    try:
                        n_chunks = _write_knowledge_chunks(
                            source, text, provenance='external_authority', tags=sf_tags,
                            attribution=f"{source.source_name} — SmartFarmKorea 실측 데이터",
                        )
                        messages["info"].append(f"Knowledge digest: {n_chunks} chunk(s) processed.")
                    except Exception as digest_exc:
                        logger.warning(
                            "Knowledge digest failed for source_id=%s: %s", source_id, digest_exc
                        )
                        messages["warning"].append(f"Knowledge digest failed: {digest_exc}")
                else:
                    messages["warning"].append(
                        "knowledge_digest_enabled is off — fetched data was not added to the AI knowledge index."
                    )
        else:
            # Dispatch by source_type (existing logic — unchanged)
            value = None
            if source.source_type == 'rest_api':
                value, err = _fetch_rest_api(source, config)
            elif source.source_type == 'document':
                value, err = _parse_document(source, config)
            elif source.source_type == 'google_drive':
                value, err = _fetch_google_drive(source, config)
            elif source.source_type == 'web_url':
                value, err = _fetch_web_url(source, config)
            elif source.source_type == 'internal_query':
                value, err = _run_internal_query(source, config)
            else:
                err = f"Unknown source_type: {source.source_type}"
                value = None

            if not err and value is not None:
                records = [{'parameter_name': source.parameter_name, 'value': str(value)}]
                raw_payload = str(value)[:10000]

                # @ANCHOR: KNOWLEDGE_DIGEST_HOOK [2026-07-07]
                # Document/web_url sources hold prose worth chunking + digesting
                # for the knowledge_search index. rest_api/internal_query results
                # are typically short structured JSON — left as plain
                # AIContextRecord values, unchanged.
                if source.source_type in ('document', 'web_url', 'google_drive') and _digest_enabled():
                    try:
                        n_chunks = _write_knowledge_chunks(source, str(value))
                        messages["info"].append(f"Knowledge digest: {n_chunks} chunk(s) processed.")
                    except Exception as digest_exc:
                        logger.warning(
                            "Knowledge digest failed for source_id=%s: %s", source_id, digest_exc
                        )
                        messages["warning"].append(f"Knowledge digest failed: {digest_exc}")

        if err:
            source.last_sync_status = 'error'
            source.last_synced_at = datetime.utcnow()
            db.session.commit()
            messages["error"].append(err)
            # @ANCHOR: SYNC_LOG_WRITE_ERROR
            _write_sync_log(
                source_id=source_id,
                source=source,
                config=config,
                raw_payload=None,
                records_written=0,
                sync_status='error',
                error_message=err[:2000],
            )
            return messages

        count = _write_context_records(source, records or [])
        messages["records_written"] = count

        source.last_synced_at = datetime.utcnow()
        source.last_sync_status = 'ok'
        db.session.commit()

        messages["success"].append(
            f"Synced source '{source.source_name}' → {count} record(s) written."
        )
        # @ANCHOR: SYNC_LOG_WRITE_SUCCESS
        _write_sync_log(
            source_id=source_id,
            source=source,
            config=config,
            raw_payload=raw_payload,
            records_written=count,
            sync_status='ok',
            error_message=None,
        )

    except Exception as exc:
        logger.exception("sync_source failed for source_id=%s", source_id)
        db.session.rollback()
        messages["error"].append(str(exc))
        # @ANCHOR: SYNC_LOG_WRITE_EXCEPTION
        _write_sync_log(
            source_id=source_id,
            source=source,
            config=config,
            raw_payload=None,
            records_written=0,
            sync_status='error',
            error_message=str(exc)[:2000],
        )

    return messages


# @ANCHOR: DISPATCH_EXT_CLIENT
def _dispatch_ext_client(source, config, preset_key):
    """
    Ext client interface contract:
        All ext clients must implement:
            def sync(self, facility_id: str, config: dict) -> list[dict]:
                Returns list of {'parameter_name': str, 'value': str} dicts.
                May return an empty list on error (log internally).

    Dynamically imports and invokes the ext client class registered in EXT_CLIENT_MAP.
    Returns list[dict] on success, or {'error': str} on import/invocation failure.
    If the client module is not yet implemented, logs a warning and returns an error dict
    so the caller can record the sync as failed without raising an exception.
    """
    import importlib

    class_path = EXT_CLIENT_MAP.get(preset_key, '')
    if not class_path:
        return {'error': f'No class mapped for preset_key: {preset_key}'}

    module_path, class_name = class_path.rsplit('.', 1)
    try:
        module = importlib.import_module(module_path)
        client_cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        logger.warning("Ext client %s not yet implemented: %s", preset_key, exc)
        return {'error': f'Ext client {preset_key} not yet implemented.'}

    try:
        client = client_cls()
        records = client.sync(facility_id=source.facility_id, config=config)
        return records if isinstance(records, list) else []
    except Exception as exc:
        logger.exception("Ext client %s sync() failed", preset_key)
        return {'error': f'Ext client {preset_key} sync() raised: {exc}'}


# @ANCHOR: WRITE_CONTEXT_RECORDS
def _write_context_records(source, records):
    """
    Upsert a list of records into AIContextRecord.

    Supports two input formats:
        - list[dict]:  [{'parameter_name': str, 'value': str}, ...]
        - list[tuple]: [(param_name, value), ...]

    For each record:
        - If a row with (facility_id, parameter_name, source) already exists: update value.
        - Otherwise: insert a new AIContextRecord.
    Commits once after all records are written.
    Returns count of records written.
    """
    if not records:
        return 0

    count = 0
    for rec in records:
        # Normalise to (param, val) regardless of input type
        if isinstance(rec, dict):
            param = rec.get('parameter_name', '')
            val = rec.get('value', '')
        elif isinstance(rec, (list, tuple)) and len(rec) >= 2:
            param = rec[0]
            val = rec[1]
        else:
            continue

        if not param:
            continue

        existing = AIContextRecord.query.filter_by(
            facility_id=source.facility_id,
            parameter_name=param,
            source=source.source_id,
        ).first()

        if existing:
            existing.value = val
        else:
            db.session.add(AIContextRecord(
                facility_id=source.facility_id,
                parameter_name=param,
                value=val,
                source=source.source_id,
                context_state='system_generated',
                created_by='sync',
            ))

        count += 1

    db.session.commit()
    return count


# @ANCHOR: FETCH_REST_API
def _fetch_rest_api(source, config):
    """
    Fetch value from an external REST API endpoint.

    config keys:
        endpoint_url (str): Target URL
        method (str): 'GET' or 'POST' (default: 'GET')
        auth_type (str): 'none', 'bearer', 'api_key' (default: 'none')
        auth_value (str): Token or key value
        json_path (str): Dot-notation path to extract from response JSON (e.g. 'data.value')
    """
    try:
        import requests

        url = config.get('endpoint_url', '')
        if not url:
            return None, "endpoint_url is required for rest_api source."

        method = config.get('method', 'GET').upper()
        auth_type = config.get('auth_type', 'none')
        auth_value = config.get('auth_value', '')
        json_path = config.get('json_path', '')

        headers = {}
        if auth_type == 'bearer':
            headers['Authorization'] = f'Bearer {auth_value}'
        elif auth_type == 'api_key':
            headers['X-API-Key'] = auth_value

        if method == 'POST':
            resp = requests.post(url, headers=headers, timeout=10)
        else:
            resp = requests.get(url, headers=headers, timeout=10)

        resp.raise_for_status()
        data = resp.json()

        # Extract value via dot-notation path
        if json_path:
            for key in json_path.split('.'):
                if isinstance(data, dict):
                    data = data.get(key)
                else:
                    data = None
                if data is None:
                    break

        return json.dumps(data), None

    except Exception as exc:
        return None, f"rest_api fetch error: {exc}"


# @ANCHOR: EXTRACT_PDF_TEXT
def _extract_pdf_text(path):
    """Extract plain text from a PDF file using pdfplumber.

    Returns extracted text on success, or a descriptive error string if
    pdfplumber is not installed or extraction fails (soft failure — caller
    stores the message as context value rather than raising).
    """
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages_text = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages_text.append(t.strip())
        return '\n\n'.join(pages_text)
    except ImportError:
        return f'[PDF parsing unavailable: pdfplumber not installed. File: {path.name}]'
    except Exception as exc:
        logger.warning('PDF extraction failed for %s: %s', path, exc)
        return f'[PDF extraction failed: {exc}]'


# @ANCHOR: PARSE_DOCUMENT
def _parse_document(source, config):
    """
    Extract text content from a local file path.

    config keys:
        file_path (str): Path to the file (relative paths resolved from app root)
        parse_mode (str): 'full_text', 'summary', 'key_value' (default: 'full_text')

    PDF files (.pdf) are extracted via pdfplumber. All other files are read as
    UTF-8 text with a latin-1 fallback for binary-safe decoding.
    """
    try:
        file_path = config.get('file_path', '')
        if not file_path:
            return None, "file_path is required for document source."

        path = pathlib.Path(file_path)
        if not path.exists():
            return None, f"File not found: {file_path}"

        # Route by file extension
        if path.suffix.lower() == '.pdf':
            content = _extract_pdf_text(path)
        else:
            try:
                content = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                content = path.read_text(encoding='latin-1', errors='replace')

        if not content or not content.strip():
            return None, "No text content extracted from file"

        parse_mode = config.get('parse_mode', 'full_text')
        if parse_mode == 'full_text':
            value = content
        elif parse_mode == 'key_value':
            # Simple key=value extraction
            pairs = {}
            for line in content.splitlines():
                if '=' in line:
                    k, _, v = line.partition('=')
                    pairs[k.strip()] = v.strip()
            value = json.dumps(pairs)
        else:
            # Default: return first 1000 chars as summary
            value = content[:1000]

        return value, None

    except Exception as exc:
        return None, f"document parse error: {exc}"


# @ANCHOR: FETCH_GOOGLE_DRIVE
def _fetch_google_drive(source, config):
    """
    Fetch + concatenate text from one or more files the operator picked via
    the Google Picker (aot/aot_flask/templates/pages/ai/ai_library.html).

    Reuses the SAME per-user OAuth connection Calendar sync uses
    (UserCalendarConnection, provider='google') — Drive access is just the
    additional drive.file scope on that one connection (see
    aot/utils/google_oauth.py SCOPES), not a separate credential store. This
    is why a source-level api_key field doesn't exist here: the credential
    lives with the connecting USER, not the source.

    config keys:
        connected_user_id (int): AoT user id whose Google connection to use —
            sync can run unattended via APScheduler with no "current user",
            so this must be persisted at pick time, not read from
            flask_login.current_user.
        files (list[{id, name}]): Drive fileIds picked via the Picker.

    Each file is downloaded/exported (aot.utils.google_drive_api), written to
    a temp file, and parsed via the EXISTING _parse_document (so PDF/text
    extraction logic is not duplicated). A single failing file is skipped
    (logged) rather than failing the whole sync — best-effort over an
    operator-picked batch, matching the "partial success" behaviour of the
    SmartFarmKorea multi-operation digest above.
    """
    import os
    import tempfile

    user_id = config.get('connected_user_id')
    files = config.get('files') or []
    if not user_id:
        return None, "No Google account connected for this source — reopen the settings modal and pick files again."
    if not files:
        return None, "No files selected — pick at least one file from Google Drive."

    from aot.databases.models.calendar_integration import UserCalendarConnection
    connection = UserCalendarConnection.query.filter_by(user_id=user_id, provider='google').first()
    if not connection or not connection.get_refresh_token():
        return None, "Google account is not connected — connect it under Settings > Integrations, then reopen this source and pick files again."

    # A connection made before drive.file was added to SCOPES (google_oauth.py)
    # still refreshes access_tokens fine (Google honors the old, narrower
    # grant) but every Drive call on that token 403s PERMISSION_DENIED —
    # confirmed live 2026-07-21. Catch it here with a clear message instead
    # of a raw API error, even though the settings-modal picker already
    # blocks picking files in this state (defense in depth: the source may
    # have been picked before the account's Drive access was later revoked
    # from Google's own security settings, without AoT being told).
    if 'drive.file' not in (connection.scope or ''):
        return None, ("Google account is connected but was authorized before Drive access was added — "
                       "reconnect it under Settings > Integrations to grant Drive access, then reopen this "
                       "source and pick files again.")

    # Reused, not duplicated: calendar_sync_service already implements
    # refresh-if-expired against this exact connection/token-pair shape.
    from aot.ai.services.calendar_sync_service import get_valid_access_token
    access_token = get_valid_access_token(connection)
    if not access_token:
        return None, "Could not refresh the Google access token — reconnect the account under Settings > Integrations."

    from aot.utils import google_drive_api

    text_blocks = []
    failures = []
    for f in files:
        file_id = (f or {}).get('id')
        display_name = (f or {}).get('name') or file_id
        if not file_id:
            continue
        content_bytes, filename, err = google_drive_api.fetch_file_content(access_token, file_id)
        if err:
            failures.append(f"{display_name}: {err}")
            logger.warning("Google Drive fetch failed for file %s (%s): %s", file_id, display_name, err)
            continue

        suffix = pathlib.Path(filename).suffix or '.txt'
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content_bytes)
                tmp_path = tmp.name
            text, perr = _parse_document(source, {'file_path': tmp_path, 'parse_mode': 'full_text'})
            if perr:
                failures.append(f"{filename}: {perr}")
                logger.warning("Google Drive parse failed for file %s: %s", filename, perr)
                continue
            text_blocks.append(f"### {filename}\n{text}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    if not text_blocks:
        return None, ('; '.join(failures) if failures else
                       "No text extracted from the selected Google Drive files.")
    return '\n\n'.join(text_blocks), None


# @ANCHOR: FETCH_WEB_URL
def _fetch_web_url(source, config):
    """
    Scrape a web page and optionally extract content via CSS selector.

    config keys:
        url (str): Target URL
        css_selector (str): Optional CSS selector for element extraction
    """
    try:
        import requests

        url = config.get('url', '')
        if not url:
            return None, "url is required for web_url source."

        resp = requests.get(url, timeout=15, headers={'User-Agent': 'AoT-Sync/1.0'})
        resp.raise_for_status()
        html = resp.text

        css_selector = config.get('css_selector', '').strip()
        soup = BeautifulSoup(html, 'html.parser')
        if css_selector:
            elements = soup.select(css_selector)
            value = ' '.join(el.get_text(strip=True) for el in elements)
        else:
            # No selector: return plain text of full page (truncated)
            value = soup.get_text(separator=' ', strip=True)[:3000]

        return value, None

    except Exception as exc:
        return None, f"web_url fetch error: {exc}"


# @ANCHOR: RUN_INTERNAL_QUERY
def _run_internal_query(source, config):
    """
    Execute a parameterized SQL query against the application database.

    config keys:
        query_template (str): SQL query (use :param_name placeholders for safety)
        params (dict): Optional parameter bindings for the query
    """
    try:
        from sqlalchemy import text

        query_template = config.get('query_template', '')
        if not query_template:
            return None, "query_template is required for internal_query source."

        params = config.get('params', {})

        with db.engine.connect() as conn:
            result = conn.execute(text(query_template), params)
            rows = [dict(row._mapping) for row in result]

        value = json.dumps(rows)
        return value, None

    except Exception as exc:
        return None, f"internal_query error: {exc}"


# @ANCHOR: WRITE_SYNC_LOG
def _write_sync_log(source_id, source, config, raw_payload,
                    records_written, sync_status, error_message):
    """
    Write one AILibrarySyncLog row for the current sync attempt.
    Silently absorbs any DB error to avoid masking the original sync result.
    Calls _prune_sync_log() after commit to retain only the most recent 20 rows.
    """
    try:
        log = AILibrarySyncLog()
        log.source_id = source_id
        log.facility_id = source.facility_id if source else ''
        log.source_type = getattr(source, 'source_type', 'unknown') if source else 'unknown'
        log.preset_key = config.get('preset_key', '') if config else ''
        log.raw_payload = raw_payload
        log.records_written = records_written
        log.sync_status = sync_status
        log.error_message = error_message
        db.session.add(log)
        db.session.commit()
        _prune_sync_log(source_id)
    except Exception as log_exc:
        logger.warning("Failed to write AILibrarySyncLog for source_id=%s: %s",
                       source_id, log_exc)
        try:
            db.session.rollback()
        except Exception:
            pass


# @ANCHOR: PRUNE_SYNC_LOG
def _prune_sync_log(source_id, keep_last=20):
    """
    Delete AILibrarySyncLog rows for source_id beyond the most recent keep_last rows.
    Silently absorbs any DB error.
    """
    try:
        rows = (
            AILibrarySyncLog.query
            .filter_by(source_id=source_id)
            .order_by(AILibrarySyncLog.synced_at.desc())
            .all()
        )
        if len(rows) > keep_last:
            for old_row in rows[keep_last:]:
                db.session.delete(old_row)
            db.session.commit()
    except Exception as prune_exc:
        logger.warning("Failed to prune AILibrarySyncLog for source_id=%s: %s",
                       source_id, prune_exc)
        try:
            db.session.rollback()
        except Exception:
            pass


# ============================================================================
# Knowledge digest pipeline (Phase 6) — chunk + LLM-digest document/web_url
# source text at sync time so query-time retrieval is pure DB lookup.
# See .local/plans/phase6_knowledge_digest_design.md.
# ============================================================================

_CHUNK_TARGET_CHARS = 2500
_CHUNK_MAX_CHARS = 4000

_DIGEST_PROMPT_TEMPLATE = (
    "다음은 IoT 농장 운영 AI가 참고할 지식 소스 '{source_name}'의 한 구간이다. "
    "AI가 답변 근거로 인용할 수 있도록 아래 JSON 형식으로만 응답하라(다른 텍스트 금지):\n"
    '{{"section_title": "이 구간을 대표하는 짧은 제목", '
    '"digest_text": "핵심 수치·조건·임계값은 보존하고 서사는 제거한 한국어 요약(500자 이내)", '
    '"keywords": ["검색에 쓸 키워드/도메인 별칭 3~8개"]}}\n\n'
    "--- 원문 구간 ---\n{chunk_text}\n--- 원문 구간 끝 ---"
)


# @ANCHOR: KNOWLEDGE_DIGEST_ENABLED
def _digest_enabled():
    """True if the knowledge digest feature flag is on. Any error → False
    (fail closed — sync must keep working exactly as before when unsure)."""
    try:
        s = AIGlobalSettings.query.first()
        return bool(s and getattr(s, 'knowledge_digest_enabled', False))
    except Exception:
        return False


# @ANCHOR: SPLIT_CHUNKS
def _split_chunks(text):
    """Deterministically split `text` into ~target-sized chunks on paragraph
    boundaries. A markdown heading (short line starting with '#') starts a new
    chunk when the current buffer already has content, keeping sections
    coherent. Chunks over _CHUNK_MAX_CHARS are hard-split; tiny trailing
    fragments (<200 chars) are merged into the previous chunk."""
    text = (text or '').strip()
    if not text:
        return []

    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    buf, buf_len = [], 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        is_heading = bool(re.match(r'^#{1,6}\s+\S', para)) and len(para) < 200
        if is_heading and buf:
            chunks.append('\n\n'.join(buf))
            buf, buf_len = [], 0
        buf.append(para)
        buf_len += len(para)
        if buf_len >= _CHUNK_TARGET_CHARS:
            chunks.append('\n\n'.join(buf))
            buf, buf_len = [], 0
    if buf:
        chunks.append('\n\n'.join(buf))

    merged = []
    for c in chunks:
        if merged and len(c) < 200:
            merged[-1] = merged[-1] + '\n\n' + c
        else:
            merged.append(c)

    out = []
    for c in merged:
        if len(c) <= _CHUNK_MAX_CHARS:
            out.append(c)
        else:
            for i in range(0, len(c), _CHUNK_MAX_CHARS):
                out.append(c[i:i + _CHUNK_MAX_CHARS])
    return out


# @ANCHOR: PICK_DIGESTER_AGENT
def _pick_digester_agent():
    """Prefer a dedicated 'digester' pipeline_role agent; fall back to the
    synthesizer/supervisor agent already used for periodic advice generation
    (ai_summary_service) rather than provisioning new infrastructure."""
    from aot.databases.models import AIAgent
    return (
        AIAgent.query.filter_by(pipeline_role='digester', is_activated=True).first()
        or AIAgent.query.filter_by(pipeline_role='synthesizer', is_activated=True).first()
        or AIAgent.query.filter_by(role='supervisor', is_activated=True).first()
    )


# @ANCHOR: DIGEST_ONE_CHUNK
def _digest_one(chunk_text, source_name):
    """LLM-digest one chunk into {section_title, digest_text, keywords}.

    Never raises — any failure (no agent configured, engine error, malformed
    JSON) soft-falls back to a truncated raw excerpt so a bad digest never
    aborts the whole sync. Callers persist whatever this returns.
    """
    fallback = {
        'section_title': (source_name or '지식')[:255],
        'digest_text': chunk_text[:1000],
        'keywords': '',
    }
    try:
        from aot.ai.services.ai_agent_service import AIAgentService

        agent = _pick_digester_agent()
        if not agent:
            return fallback

        engine = AIAgentService.get_engine(agent.unique_id)
        if not engine:
            return fallback
        prompt = _DIGEST_PROMPT_TEMPLATE.format(
            source_name=source_name or '', chunk_text=chunk_text[:6000]
        )
        result = engine.run_reasoning({}, prompt)
        if not isinstance(result, dict):
            return fallback

        title = str(result.get('section_title') or fallback['section_title'])[:255]
        digest = str(result.get('digest_text') or '').strip()
        kw = result.get('keywords')
        if isinstance(kw, list):
            keywords = ','.join(str(k).strip() for k in kw if str(k).strip())
        else:
            keywords = str(kw or '').strip()

        if not digest:
            return fallback
        return {'section_title': title, 'digest_text': digest, 'keywords': keywords}
    except Exception as exc:
        logger.warning("Knowledge chunk digest failed, using excerpt fallback: %s", exc)
        return fallback


# @ANCHOR: WRITE_KNOWLEDGE_CHUNKS
def _write_knowledge_chunks(source, text, provenance='user_provided', tags=None, attribution=None):
    """Chunk + digest `text` and upsert AIKnowledgeChunk rows for `source`.

    Chunks whose content_hash matches a prior sync are kept as-is (no LLM
    re-digest — re-syncing an unchanged document costs zero LLM calls).
    Chunks that no longer appear in the source (doc shrank/changed) are
    disabled rather than deleted, preserving any review history.
    Returns count of chunks written (created or refreshed).

    provenance/tags/attribution let a system ext source (e.g. SmartFarmKorea,
    see @ANCHOR: SMARTFARMKOREA_DIGEST) reuse this same chunk+digest+dedup
    pipeline instead of duplicating it, while still being tagged
    'external_authority' (not the 'user_provided' default this function was
    written for — a document/web_url source the operator registered
    themselves) — see docs/design/ai-library-redesign.md §2-3.
    """
    chunks = _split_chunks(text)
    if not chunks:
        return 0

    existing_by_hash = {
        row.content_hash: row
        for row in AIKnowledgeChunk.query.filter_by(source_id=source.source_id).all()
    }
    seen_hashes = set()
    count = 0
    tags_str = ','.join(tags) if isinstance(tags, (list, tuple)) else (tags or None)

    for idx, chunk_text in enumerate(chunks):
        content_hash = hashlib.sha256(chunk_text.encode('utf-8')).hexdigest()
        seen_hashes.add(content_hash)
        row = existing_by_hash.get(content_hash)
        if row:
            row.chunk_index = idx
            row.is_enabled = True
            row.facility_id = source.facility_id  # keep in sync if the source was reassigned
            count += 1
            continue

        digested = _digest_one(chunk_text, source.source_name)
        db.session.add(AIKnowledgeChunk(
            source_id=source.source_id,
            source_name=source.source_name,
            facility_id=source.facility_id,
            section_title=digested['section_title'],
            digest_text=digested['digest_text'],
            keywords=digested['keywords'],
            raw_excerpt=chunk_text[:4000],
            chunk_index=idx,
            content_hash=content_hash,
            context_state='system_generated',
            is_enabled=True,
            provenance=provenance,
            content_kind='prose',
            tags=tags_str,
            attribution=attribution or f"{source.source_name} ({source.source_type})",
        ))
        count += 1

    for content_hash, row in existing_by_hash.items():
        if content_hash not in seen_hashes:
            row.is_enabled = False

    db.session.commit()
    return count
