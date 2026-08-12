# coding=utf-8
"""알림 박스(.aot-notice-box) 테두리색의 custom_ui 4곳 일치 계약 + 업그레이드
페이지 타이포그래피 회귀 가드.

배경(2026-08-12): 사용자가 "배경·문자색은 어디서 참고했나" 라고 물어 확인해보니
이미 settings/custom_ui 로 연동돼 있었지만(--aot-tint-*-bg/fg), 테두리는
정적 --aot-border-neutral 로 고정돼 있었다 — "테두리도 연동해달라" 는 후속
요청으로 tint_{success,warning,danger,info}_border 4개 필드를 추가했다.

docs/design/color-system.md 는 같은 기본값이 4곳에 있고 항상 일치해야 한다고
명시한다(§3). 어느 한 곳만 갱신하면 "폼에는 새 색이 보이는데 저장하면 반영 안
됨" 류의 조용한 드리프트가 난다 — 이 파일이 그 계약을 코드로 고정한다.
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

BORDER_FIELDS = ['tint_success_border', 'tint_warning_border',
                 'tint_danger_border', 'tint_info_border']


def test_border_fields_in_theme_color_fields():
    """forms_settings.THEME_COLOR_FIELDS 가 저장/로드 루프를 구동하는 유일한
    목록이다 (utils_settings.settings_custom_ui_mod) -- 여기 없으면 폼에
    입력창이 있어도 절대 저장되지 않는다."""
    sys.path.insert(0, str(REPO))
    from aot.aot_flask.forms.forms_settings import THEME_COLOR_FIELDS
    for field in BORDER_FIELDS:
        assert field in THEME_COLOR_FIELDS, field


def test_border_fields_have_form_fields():
    """StringField 선언이 없으면 settings/custom_ui.html 의
    form_settings_custom_ui[field_name] 렌더링이 Jinja UndefinedError 로 죽는다."""
    text = FORMS_SETTINGS.read_text()
    for field in BORDER_FIELDS:
        assert re.search(rf'^\s*{field}\s*=\s*StringField\(', text, re.MULTILINE), field


def test_border_fields_wired_to_real_tokens():
    """/custom.css 발행 로직(routes_general.custom_css) 이 필드를 실제
    --aot-* 토큰으로 내보내지 않으면, 폼에서 바꿔도 화면 색이 절대 안 바뀐다."""
    text = ROUTES_GENERAL.read_text()
    for field, token in zip(
            BORDER_FIELDS,
            ['--aot-tint-success-border', '--aot-tint-warning-border',
             '--aot-tint-danger-border', '--aot-tint-info-border']):
        m = re.search(rf"'{field}':\s*\[([^\]]+)\]", text)
        assert m, f"{field} 가 var_map 에 없다"
        assert token in m.group(1), f"{field} -> {token} 매핑 없음: {m.group(1)}"


def test_border_defaults_agree_across_four_places():
    """color-system.md §3 의 '기본값 4곳 일치' 계약. 이번엔 3곳
    (theme-variables.css 실토큰 / theme_defaults.json / custom_ui.html
    SEMANTIC_DEFAULTS) + forms_settings 폴백까지 4곳을 직접 비교한다."""
    theme_vars_text = THEME_VARS.read_text()
    css_defaults = {}
    for m in re.finditer(
            r'--aot-tint-(success|warning|danger|info)-border:\s*(#[0-9a-fA-F]{6});',
            theme_vars_text):
        css_defaults[f'tint_{m.group(1)}_border'] = m.group(2).upper()
    assert len(css_defaults) == 4, css_defaults

    import json
    json_defaults = json.loads(THEME_DEFAULTS_JSON.read_text())

    custom_ui_text = CUSTOM_UI_HTML.read_text()
    m = re.search(r'tint_success_border:\s*\'(#[0-9A-Fa-f]{6})\'.*?'
                  r'tint_warning_border:\s*\'(#[0-9A-Fa-f]{6})\'.*?'
                  r'tint_danger_border:\s*\'(#[0-9A-Fa-f]{6})\'.*?'
                  r'tint_info_border:\s*\'(#[0-9A-Fa-f]{6})\'',
                  custom_ui_text, re.S)
    assert m, "custom_ui.html SEMANTIC_DEFAULTS 에서 4개 border 값을 못 찾음"
    custom_ui_defaults = {
        'tint_success_border': m.group(1).upper(),
        'tint_warning_border': m.group(2).upper(),
        'tint_danger_border': m.group(3).upper(),
        'tint_info_border': m.group(4).upper(),
    }

    sys.path.insert(0, str(REPO))
    from aot.aot_flask.forms import forms_settings
    for field in BORDER_FIELDS:
        css_val = css_defaults[field]
        json_val = json_defaults[field].upper()
        ui_val = custom_ui_defaults[field]
        assert css_val == json_val == ui_val, (
            f"{field} 불일치: theme-variables.css={css_val} "
            f"theme_defaults.json={json_val} custom_ui.html={ui_val}")


def _strip_css_comments(css_text):
    return re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)


def _find_rule_body(css_text, selector):
    """selector 로 시작하는 실제 규칙 블록만 찾는다. /* ... */ 주석을 먼저
    걷어낸다 -- 이 파일의 설명 주석 안에 같은 셀렉터가 예시로 백틱 인용돼
    있어, 주석을 안 걷으면 그 예시 텍스트를 진짜 규칙으로 오인한다."""
    stripped = _strip_css_comments(css_text)
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', stripped)
    return m.group(1) if m else None


def test_notice_box_consumes_per_tint_border_not_flat_neutral():
    """.aot-notice-box 가 다시 --aot-border-neutral(정적, custom_ui 밖) 하나로
    묶이면 이 계약 전체가 무의미해진다 -- plain 변형만 예외(안내문이 아니라
    폼을 감싸는 용도라 시맨틱 톤이 없다)."""
    stripped = _strip_css_comments(MODAL_CSS.read_text())
    box_start = stripped.index('.aot-notice-box {')
    plain_start = stripped.index('.aot-notice-box-plain')
    body = stripped[box_start:plain_start]
    assert '--aot-border-neutral' not in body
    for token in ('--aot-tint-warning-border', '--aot-tint-success-border',
                  '--aot-tint-danger-border', '--aot-tint-info-border'):
        assert token in body, token


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
