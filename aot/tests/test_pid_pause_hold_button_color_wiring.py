# coding=utf-8
"""settings/custom_ui 의 "일시중지"(bg_btn_pause)/"유지"(bg_btn_hold) 가
실제 PID Pause/Hold 버튼에 연결돼 있는지 고정한다.

2026-09-08 발견: custom_ui 미리보기(6개 버튼 상태 — 켜기/끄기/활성/비활성/
일시중지/유지)는 시스템 색상의 유일한 정본이라는 게 이 세션에서 재확인된
규칙이다. 그런데 `--aot-btn-bg-pause`/`--aot-btn-bg-hold` 는 CSS 변수와
var_map 배선까지는 있었지만, 그 색을 실제로 쓰는 버튼 클래스가 앱 어디에도
없었다 — PID 의 실제 Pause/Hold 버튼(function_options/pid_entry.html)이
`aot-pill-btn-primary`(전역 주 버튼, btn_primary_bg 소비)를 대신 쓰고
있어서, "일시중지"/"유지" 값을 바꿔도 화면 어디에도 반영되지 않았다.

docs/design/color-system.md §5-13 (bg_btn_on/off 사고)의 일반형 — "필드는
선언돼 있는데 실제 소비처가 없다"는, 아직 그 문서가 다루지 않는 별도의
실패 모드다.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROUTES = REPO / "aot" / "aot_flask" / "routes_general.py"
THEME_VARS = REPO / "aot" / "aot_flask" / "static" / "css" / "aot-theme-variables.css"
MODAL_MODERN = REPO / "aot" / "aot_flask" / "static" / "css" / "aot-modal-modern.css"
PID_ENTRY = REPO / "aot" / "aot_flask" / "templates" / "pages" / "function_options" / "pid_entry.html"


class PidPauseHoldButtonColorWiringTest(unittest.TestCase):
    def test_var_map_declares_pause_and_hold_tokens(self):
        text = ROUTES.read_text(encoding="utf-8")
        for field, token in [
            ("bg_btn_pause", "--aot-btn-bg-pause"),
            ("bg_btn_hold", "--aot-btn-bg-hold"),
        ]:
            m = re.search(rf"'{field}':\s*\[([^\]]+)\]", text)
            self.assertIsNotNone(m, f"{field} 가 var_map 에 없다")
            self.assertIn(token, m.group(1), f"{field} -> {token} 매핑이 없다")

    def test_pid_pause_and_hold_buttons_use_their_own_class_not_primary(self):
        """Pause/Hold 버튼이 aot-pill-btn-primary(전역 주 버튼, btn_primary_bg)
        가 아니라 각자 전용 클래스를 쓴다 — 안 그러면 "일시중지"/"유지" 설정이
        아니라 "활성" 설정에 묶여 버린다."""
        text = PID_ENTRY.read_text(encoding="utf-8")
        pause_input = re.search(r'name="pid_pause"[^>]*class="([^"]+)"', text)
        hold_input = re.search(r'name="pid_hold"[^>]*class="([^"]+)"', text)
        self.assertIsNotNone(pause_input, "pid_pause 버튼을 못 찾았다")
        self.assertIsNotNone(hold_input, "pid_hold 버튼을 못 찾았다")
        self.assertIn("aot-pill-btn-pause", pause_input.group(1))
        self.assertNotIn("aot-pill-btn-primary", pause_input.group(1))
        self.assertIn("aot-pill-btn-hold", hold_input.group(1))
        self.assertNotIn("aot-pill-btn-primary", hold_input.group(1))

    def test_pause_and_hold_classes_consume_their_own_token_in_css(self):
        text = re.sub(r"/\*.*?\*/", "", MODAL_MODERN.read_text(encoding="utf-8"),
                      flags=re.S)
        pause_body = re.search(
            r"\.btn\.aot-pill-btn\.aot-pill-btn-pause\s*\{([^}]*)\}", text)
        hold_body = re.search(
            r"\.btn\.aot-pill-btn\.aot-pill-btn-hold\s*\{([^}]*)\}", text)
        self.assertIsNotNone(pause_body, ".aot-pill-btn-pause 규칙이 없다")
        self.assertIsNotNone(hold_body, ".aot-pill-btn-hold 규칙이 없다")
        self.assertIn("--aot-btn-bg-pause", pause_body.group(1))
        self.assertIn("--aot-btn-bg-hold", hold_body.group(1))

    def test_pause_hold_tokens_are_not_aliased_to_the_primary_field(self):
        """--aot-btn-bg-pause/-hold 가 bg_btn_on 사고처럼 다른 필드
        (btn_primary_bg 의 --aot-btn-bg-active 등)로 슬쩍 다시 합쳐지지
        않았는지 확인한다."""
        text = THEME_VARS.read_text(encoding="utf-8")
        m = re.search(r"--aot-btn-bg-pause:\s*([^;]+);", text)
        self.assertIsNotNone(m, "--aot-btn-bg-pause 정의를 못 찾았다")
        self.assertNotIn("var(", m.group(1),
                         "--aot-btn-bg-pause 가 다른 토큰의 별칭이 되어버렸다 "
                         "— 자기 고유 색이어야 한다")


if __name__ == "__main__":
    unittest.main()
