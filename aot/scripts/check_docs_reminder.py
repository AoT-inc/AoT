#!/usr/bin/env python3
"""매뉴얼 최신화 리마인더 — 기능 코드만 바뀌고 docs/ 는 그대로인 커밋을 알아챈다.

## 왜 있는가

`aot/scripts/check_docs_health.py` (+ `.github/workflows/docs-health.yml`) 는
`docs/` 안의 내적 일관성(링크·앵커·i18n 완역도·버전·이미지)만 검사한다.
트리거 경로도 `docs/**` 가 바뀌었을 때만 돈다 — **기능 코드가 바뀌었는데
`docs/` 가 안 바뀐 경우를 잡는 장치는 그동안 전혀 없었다.**

2026-09-18 매뉴얼 감사에서 이게 실제로 문제였다: `docs/geo/*.md` 5쪽과
`docs/Notices.md` 가 최대 4개월 동안 UI 재설계·필드명 변경·신규 기능을 놓친
채로 남아 있었다(예: `save_as_site` API 문서가 실제 필드명과 아예 달라
문서대로 호출하면 실패했다, AI 조언 패널이 "가짜 데이터지만 승인 버튼은
실제 명령을 보낸다"는 코드 내 경고가 문서에 없었다 등). 그때까지 유일한
안전장치는 Claude 의 개인 메모리(커밋 전에 문서를 점검하라는 지시)뿐이었고
사람이 직접 커밋할 때는 아무 견제도 없었다.

## 이 검사가 하는 일과 하지 않는 일

**한다**: 스테이지된 파일이 아래 WATCH_AREAS 의 코드 경로에 속하는데, 같은
커밋에 `docs/` 변경이 전혀 없으면 **경고를 띄운다**.

**하지 않는다**: 커밋을 막지 않는다. "이 변경이 매뉴얼에 반영돼야 하는
내용인가"는 리팩터링·버그 수정처럼 문서와 무관한 커밋도 섞여 있어 기계가
판정할 수 없다 — 그래서 이 훅은 항상 종료코드 0 이다(느낌표 없이 알림만).
사람이 보고 "이번엔 상관없다" 고 판단하면 그냥 진행하면 된다.

우회(메시지 자체를 끄고 싶을 때): AOT_SKIP_DOCS_REMINDER=1 git commit ...
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (표시 이름, 코드 경로 접두사들, 관련 매뉴얼 쪽) — 새 영역을 추가할 때는
# 실제로 사용자 대상 매뉴얼 쪽이 있는 코드 영역만 추가할 것. 없으면 이
# 리마인더가 채울 수 없는 경고만 늘어난다.
WATCH_AREAS = [
    (
        "AI / MCP",
        (
            "aot/ai/",
            "aot/mcp_server/",
            "aot/aot_flask/routes_ai_agent.py",
            "aot/aot_flask/routes_ai_api.py",
            "aot/aot_flask/routes_ai_context.py",
            "aot/aot_flask/routes_ai_library.py",
            "aot/aot_flask/routes_ai_monitoring.py",
            "aot/aot_flask/routes_mcp_api.py",
            "aot/config/ai_role_config.yaml",
            "aot/config/ai_action_registry.yaml",
            "aot/config/mcp_config.py",
            "aot/widgets/widget_mcp_review.py",
        ),
        ("docs/ai/", "docs/ai_guide.md"),
    ),
    (
        "GEO / 지도·시설·구획",
        (
            "aot/aot_flask/geo/",
            "aot/aot_flask/routes_geo.py",
            "aot/aot_flask/routes_geo_iec.py",
            "aot/aot_flask/templates/pages/geo/",
            "aot/aot_flask/static/js/geo/",
            "aot/databases/models/geo_",
            "aot/widgets/AoT_facility.py",
            "aot/widgets/AoT_plot.py",
            "aot/widgets/AoT_map.py",
        ),
        ("docs/geo/",),
    ),
    (
        "Scheduler",
        (
            "aot/aot_flask/routes_scheduler.py",
        ),
        ("docs/ai/scheduler.md",),
    ),
    (
        "env_coordinator (환경 제어)",
        (
            "aot/functions/custom_functions/env_coordinator.py",
            "aot/functions/custom_functions/env_coordinator_impl/",
        ),
        ("docs/ai/env-control.md",),
    ),
    (
        "공지 게시판",
        (
            "aot/aot_flask/routes_notice.py",
            "aot/databases/models/notice.py",
            "aot/widgets/widget_notice.py",
            "aot/aot_flask/templates/tools/notice",
        ),
        ("docs/Notices.md",),
    ),
]


def _staged_paths():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def main():
    if os.environ.get("AOT_SKIP_DOCS_REMINDER"):
        return 0

    staged = _staged_paths()
    if not staged:
        return 0

    docs_touched = any(p.startswith("docs/") for p in staged)
    if docs_touched:
        return 0  # 이미 문서도 같이 건드렸다 — 알릴 것 없음

    hits = []
    for label, prefixes, doc_pages in WATCH_AREAS:
        matched = [p for p in staged if p.startswith(prefixes)]
        if matched:
            hits.append((label, matched, doc_pages))

    if not hits:
        return 0

    print()
    print("[docs 리마인더] 이 커밋이 건드린 영역에 매뉴얼이 딸려 있습니다 — "
          "차단은 아니고 확인 차 알려드립니다.")
    for label, matched, doc_pages in hits:
        print(f"  - {label}: {matched[0]}"
              + (f" 외 {len(matched) - 1}개" if len(matched) > 1 else ""))
        print(f"      관련 매뉴얼: {', '.join(doc_pages)}")
    print("  이번 변경이 매뉴얼 내용에 영향이 없으면(리팩터링·버그 수정 등) 무시해도 됩니다.")
    print("  (이 메시지를 끄려면: AOT_SKIP_DOCS_REMINDER=1 git commit ...)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
