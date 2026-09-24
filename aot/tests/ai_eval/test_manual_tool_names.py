# coding=utf-8
"""The AI manuals may not name a tool that no longer exists.

docs/ai_guide*.md and docs/ai/*.md are what an agent reads to decide which tool
to call — the external MCP server hands ai_guide.ko.md out as its docs_uri, and
the pages are indexed for knowledge_search. A renamed tool therefore does not
just make the prose stale: the agent calls the old name and gets an error, or
decides the system cannot do the thing at all.

That is not hypothetical. list_plantings became list_plots (2026-08-19) and
list_reference_tables became list_lookup_sources (2026-08-25), and the guide
still advertised both weeks later.

The check is deliberately blunt: every `snake_case` token in backticks must be
either a registered tool, one of the meta tools the MCP surface adds on top of
the registry, or an identifier on the allow-list below. Adding a field name to
the allow-list is cheap; a wrong tool name costs an agent a failed call.

Run:
    python3 -m pytest aot/tests/ai_eval/test_manual_tool_names.py -q
"""
import glob
import json
import os
import re

from aot.tools.tool_registry import TOOLS

# Tools the MCP surface defines outside the registry (aot/ai/services/
# tool_execution.py:_EXTRA_TOOLS) — they have no Tool(...) declaration.
_META_TOOLS = {'open_drawer', 'get_tool_detail', 'use_tool',
               'respond_to_confirmation'}

# snake_case identifiers in the manuals that are NOT tool names: response
# fields, DB columns, config flags, module names. Keep this list explaining
# itself — an entry with no obvious source is how a typo gets grandfathered in.
_NOT_TOOLS = {
    # response fields / statuses the guide quotes
    'already_executed', 'confirmation_id', 'pending_approval',
    'evaluated_at', 'last_seen', 'farm_local',
    # model columns / flags
    'is_ai_enabled', 'config_only', 'mcp_http_enabled',
    # call arguments
    'target_name', 'target_id', 'function_type', 'device_id', 'unique_id', 'note_id',
    'tool_name', 'sensor_type', 'time_range', 'measurement_type',
    'include_ended', 'top_k', 'with_sensors',
    # 여러 대상 인자(3-F)
    'device_ids', 'loc_ids', 'plot_ids', 'target_names', 'zone_ids',
    # module / page identifiers
    'env_coordinator', 'edit_controllers', 'target_defs', 'review_page',
}

_TOKEN = re.compile(r'`([^`]+)`')
_SNAKE = re.compile(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+\Z')


def _manual_pages():
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    docs = os.path.join(root, 'docs')
    pages = sorted(glob.glob(os.path.join(docs, 'ai_guide*.md')))
    pages += sorted(glob.glob(os.path.join(docs, 'ai', '*.md')))
    return docs, pages


def test_manuals_name_only_existing_tools():
    docs, pages = _manual_pages()
    assert pages, "AI 매뉴얼을 하나도 찾지 못했다 — 경로가 바뀌었는가?"

    known = {t.name for t in TOOLS} | _META_TOOLS | _NOT_TOOLS
    unknown = {}
    for page in pages:
        with open(page, 'r', encoding='utf-8') as f:
            text = f.read()
        for raw in _TOKEN.findall(text):
            token = raw.strip()
            if _SNAKE.match(token) and token not in known:
                unknown.setdefault(token, set()).add(
                    os.path.relpath(page, docs))

    assert not unknown, (
        "AI 매뉴얼이 존재하지 않는 도구 이름을 쓰고 있다 — 도구가 개명됐거나 "
        "없어졌다면 매뉴얼을 고치고, 도구가 아니라 응답 필드·설정 이름이라면 "
        "이 파일의 _NOT_TOOLS 에 이유와 함께 추가할 것:\n" + "\n".join(
            f"  {name}: {', '.join(sorted(where))}"
            for name, where in sorted(unknown.items())))


def test_guide_core_table_matches_registry():
    """ai_guide.ko.md §1.1 이 상시 노출이라고 적은 도구는 실제로 core 여야 한다."""
    from aot.tools.tool_registry import core_tools, virtual_tools

    docs, _ = _manual_pages()
    path = os.path.join(docs, 'ai_guide.ko.md')
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()

    start = text.index('### 1.1')
    section = text[start:text.index('### 1.2', start)]
    named = {t.strip() for t in _TOKEN.findall(section)
             if _SNAKE.match(t.strip())}
    named -= _NOT_TOOLS

    mcp_core = set(core_tools()) & {p['tool_name'] for p in virtual_tools()}
    missing = mcp_core - named
    extra = named - mcp_core
    assert not missing and not extra, (
        "ai_guide.ko.md §1.1 의 상시 노출 표가 레지스트리와 어긋난다 — "
        "표에 없는 core 도구: %s / 표에만 있는 도구: %s"
        % (sorted(missing) or '없음', sorted(extra) or '없음'))


def test_index_keys_are_valid_read_manual_targets():
    """색인의 쪽 이름은 그대로 read_manual 의 target_id 여야 한다.

    AI 컨텍스트에는 이 쪽 이름 목록만 실리고(절 제목은 read_manual 이 돌려준다),
    AI 는 그 이름을 그대로 target_id 로 넘긴다. 색인 키가 docs/ 아래 실제 경로로
    풀리지 않으면 AI 는 자기가 받은 목록에 있는 쪽조차 열지 못한다.
    """
    docs, _ = _manual_pages()
    with open(os.path.join(docs, 'ai_docs', 'ai_doc_index.json'),
              'r', encoding='utf-8') as f:
        index = json.load(f)

    assert index, "매뉴얼 색인이 비어 있다"
    missing = [page for page in index
               if not os.path.isfile(os.path.join(docs, page))]
    assert not missing, (
        "색인에 있는 쪽이 docs/ 아래에 없다 — read_manual 이 열지 못한다: "
        + ", ".join(sorted(missing)))


if __name__ == '__main__':
    test_manuals_name_only_existing_tools()
    test_guide_core_table_matches_registry()
    test_index_keys_are_valid_read_manual_targets()
    print("OK")
