# coding=utf-8
"""알림 박스(.aot-notice-box) 테두리색의 custom_ui 4곳 일치 계약 + 업그레이드
페이지 타이포그래피 회귀 가드.

배경(2026-08-12): 사용자가 "배경·문자색은 어디서 참고했나" 라고 물어 확인해보니
이미 settings/custom_ui 로 연동돼 있었지만(--aot-tint-*-bg/fg), 테두리는
정적 --aot-border-neutral 로 고정돼 있었다 — "테두리도 연동해달라" 는 후속
요청으로 tint_{success,warning,danger,info}_border 4개 필드를 추가했다.

2026-09-08: 그 4개 필드를 **없앴다.** 사용처가 이 안내 상자(+ logview 두 줄)
뿐이라, 사용자가 톤마다 bg·fg·border 세 칸을 손으로 맞춰야 했다. 이제 테두리는
같은 톤의 fg 에서 파생한다(color-mix). "테두리도 테마를 따라야 한다" 는 원래
요구는 그대로 지켜지고, 정해야 할 칸만 줄었다 — 대신 테두리만 따로 다른 색으로
두는 것은 더 이상 못 한다.

이 파일은 이제 그 새 계약을 고정한다: 톤 테두리는 (1) 자기 fg 에서 나오고,
(2) 정적 --aot-border-neutral 로 다시 묶이지 않으며, (3) 색 리터럴로 박히지
않는다.
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
THEME_VARS = REPO / "aot/aot_flask/static/css/aot-theme-variables.css"
THEME_DEFAULTS_JSON = REPO / "aot/aot_flask/static/json/theme_defaults.json"
CUSTOM_UI_HTML = REPO / "aot/aot_flask/templates/settings/custom_ui.html"
FORMS_SETTINGS = REPO / "aot/aot_flask/forms/forms_settings.py"
ROUTES_GENERAL = REPO / "aot/aot_flask/routes_general.py"
MODAL_CSS = REPO / "aot/aot_flask/static/css/aot-modal-modern.css"
UPGRADE_HTML = REPO / "aot/aot_flask/templates/admin/upgrade.html"
ADMIN_UPGRADE_CSS = REPO / "aot/aot_flask/static/css/pages/admin-upgrade.css"

# 2026-09-08 에 없앤 필드들. 다시 살아나면 이 파일이 잡는다.
REMOVED_BORDER_FIELDS = ['tint_success_border', 'tint_warning_border',
                         'tint_danger_border', 'tint_info_border']


def test_removed_border_fields_stay_removed():
    """필드를 되살리려면 "왜 fg 파생으로 부족한지" 가 먼저 있어야 한다.
    그냥 다시 추가되면 사용자가 맞춰야 할 칸이 도로 늘어난다."""
    sys.path.insert(0, str(REPO))
    from aot.aot_flask.forms.forms_settings import (THEME_COLOR_FIELDS,
                                                    LEGACY_THEME_FIELDS_DROP)
    for field in REMOVED_BORDER_FIELDS:
        assert field not in THEME_COLOR_FIELDS, field
        assert field in LEGACY_THEME_FIELDS_DROP, (
            f"{field} 를 폐기 목록에 넣지 않으면 저장된 옛 값이 "
            f"custom_theme_json 에 영원히 남는다")


def test_removed_border_tokens_are_gone():
    """토큰 선언이 남아 있으면 '설정에는 없는데 CSS 는 읽는' 유령이 된다."""
    text = THEME_VARS.read_text()
    for tone in ('success', 'warning', 'danger', 'info'):
        assert f'--aot-tint-{tone}-border:' not in text, tone






def _strip_css_comments(css_text):
    return re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)


def _find_rule_body(css_text, selector):
    """selector 로 시작하는 실제 규칙 블록만 찾는다. /* ... */ 주석을 먼저
    걷어낸다 -- 이 파일의 설명 주석 안에 같은 셀렉터가 예시로 백틱 인용돼
    있어, 주석을 안 걷으면 그 예시 텍스트를 진짜 규칙으로 오인한다."""
    stripped = _strip_css_comments(css_text)
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', stripped)
    return m.group(1) if m else None


def test_notice_box_tones_derive_border_from_their_own_fg():
    """톤이 다시 --aot-border-neutral(정적, custom_ui 밖) 하나로 묶이면 이
    계약 전체가 무의미해진다.

    2026-09-07 에 표현이 바뀌었다. 예전에는 기본형이 곧 경고 톤이라
    `-warning` 변형이 없었고, 이 검사는 "`.aot-notice-box {`" 부터
    "`-plain`" 까지를 **한 덩어리로 잘라** 그 안에 네 tint 토큰이 다 있는지
    봤다. 지금은 기본형에 톤이 없고 톤 네 개가 대칭이라, 자르는 대신
    **톤마다 자기 규칙을 직접 확인한다.** 계약은 그대로다 — 사용자가
    settings/custom_ui 에서 바꾸는 값이 실제로 그 톤의 테두리에 닿아야 한다.
    """
    stripped = _strip_css_comments(MODAL_CSS.read_text())
    for tone in ('success', 'warning', 'danger', 'info'):
        sel = f'.aot-notice-box.aot-notice-box-{tone}'
        # 한 톤의 선택자는 여러 규칙에 나올 수 있다(예: 네 톤이 그림자를
        # 함께 쓰는 묶음 규칙). **색을 정하는 규칙**을 찾아야 하므로 첫
        # 규칙을 집지 말고, tint 를 담은 규칙이 하나라도 있는지 본다.
        bodies = [m.group(1) for m in re.finditer(
            re.escape(sel) + r'\s*\{([^}]*)\}', stripped)]
        assert bodies, f'{sel} 규칙이 없다'
        toned = [b for b in bodies if f'--aot-tint-{tone}-fg' in b
                 and 'border-color' in b]
        assert toned, (
            f'{sel} 의 테두리가 --aot-tint-{tone}-fg 에서 나오지 않는다: {bodies}')
        for b in toned:
            assert '--aot-border-neutral' not in b, (
                f'{sel} 가 중립 테두리로 묶였다 — custom_ui 연동이 끊긴다')
            assert not re.search(r'border-color:[^;]*#[0-9A-Fa-f]{3,8}', b), (
                f'{sel} 테두리에 색 리터럴이 박혔다 — 톤 fg 에서 파생할 것')


def test_notice_box_base_has_no_tone():
    """기본형에 톤이 없다.

    예전에는 기본형이 경고 톤이었다. 변형을 안 붙이면 조용히 노란 경고
    상자가 나왔고, 그래서 `-warning` 이라는 이름이 아예 없었다. 톤을 원하면
    붙이게 하고, 안 붙이면 톤이 없어야 한다."""
    stripped = _strip_css_comments(MODAL_CSS.read_text())
    body = _find_rule_body(stripped, '.aot-notice-box')
    assert body is not None
    for tone in ('success', 'warning', 'danger', 'info'):
        assert f'--aot-tint-{tone}' not in body, (
            f'기본형이 {tone} 톤을 갖고 있다 — 톤은 변형으로만 붙인다: {body.strip()}')


def test_upgrade_page_paragraphs_are_not_bumped_by_global_main_rule():
    """aot.css 의 `main.container > p { font-size: 1.2em !important; }` 는
    <main> 직계 자식 <p> 만 건드려, 이 페이지에서 한 단락만 다른 크기로 튀는
    원인이었다(2026-08-12). admin-upgrade.css 가 !important 로 다시 눌러야
    한다 -- 그냥 font-size 는 소스 뒤에 와도 !important 를 못 이긴다."""
    text = ADMIN_UPGRADE_CSS.read_text()
    # 파일 맨 앞 설명 주석 안에도 같은 셀렉터가 예시로 등장하므로(백틱 인용),
    # 실제 규칙(줄 시작에 오는 블록)만 골라야 한다.
    body = _find_rule_body(text, 'main.container > p')
    assert body is not None, "main.container > p 중화 규칙이 없다"
    assert '!important' in body, (
        "!important 없이는 aot.css 의 같은 규칙(!important 있음)을 못 이긴다")


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
