# coding=utf-8
"""출력 On/Off 버튼 색이 `bg_btn_on`/`bg_btn_off`(버튼 켜짐/꺼짐 — "출력 행의
ON/OFF 버튼")에 실제로 연결돼 있는지 고정한다.

2026-09-08 사용자 리포트로 발견: 레거시 별칭 정리(2026-09-07)가
`--bg-btn-on`/`--bg-btn-off` 별칭을 `btn_primary_bg`/`btn_secondary_bg`
("주/보조 버튼 배경" — 전역 저장·활성화·탭 버튼용)의 정본
`--aot-btn-bg-active`/`--aot-btn-bg-inactive` 로 잘못 합쳤다. 두 필드
기본값이 우연히 같아(#13261B/#5E6B64) 화면으로는 안 보였다 — "버튼 켜짐"
만 바꾸면 출력 화면에 반영되지 않는 것으로만 드러났다.

docs/design/color-system.md §5-13.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROUTES = REPO / "aot" / "aot_flask" / "routes_general.py"
THEME_VARS = REPO / "aot" / "aot_flask" / "static" / "css" / "aot-theme-variables.css"
ENTRY_UI = REPO / "aot" / "aot_flask" / "static" / "css" / "aot-entry-ui.css"


class OutputButtonColorWiringTest(unittest.TestCase):
    def test_bg_btn_on_off_map_to_their_own_canonical_token(self):
        """var_map 의 bg_btn_on/off 가 자기 전용 토큰을 가리킨다 —
        btn_primary_bg/secondary_bg 의 --aot-btn-bg-active/-inactive 가
        아니다(이름이 비슷해 다시 합쳐지기 쉽다)."""
        text = ROUTES.read_text(encoding="utf-8")
        for field, must_have, must_not_have in [
            ("bg_btn_on", "--aot-btn-bg-output-on", "--aot-btn-bg-active"),
            ("bg_btn_off", "--aot-btn-bg-output-off", "--aot-btn-bg-inactive"),
        ]:
            m = re.search(rf"'{field}':\s*\[([^\]]+)\]", text)
            self.assertIsNotNone(m, f"{field} 가 var_map 에 없다")
            tokens = m.group(1)
            self.assertIn(must_have, tokens,
                          f"{field} -> {must_have} 매핑이 없다: {tokens}")
            self.assertNotIn(must_not_have, tokens,
                             f"{field} 가 다시 {must_not_have}(다른 필드용)를 "
                             f"가리킨다: {tokens}")

    def test_legacy_bg_btn_alias_points_at_the_new_canonical_token(self):
        """--bg-btn-on/off (레거시 별칭)이 --aot-btn-bg-output-on/-off 를
        가리킨다 — --aot-btn-bg-active/-inactive 가 아니다."""
        text = THEME_VARS.read_text(encoding="utf-8")
        for alias, must_point_to in [
            ("--bg-btn-on", "--aot-btn-bg-output-on"),
            ("--bg-btn-off", "--aot-btn-bg-output-off"),
        ]:
            m = re.search(re.escape(alias) + r":\s*var\((--[a-z0-9-]+)", text)
            self.assertIsNotNone(m, f"{alias} 별칭 정의를 못 찾았다")
            self.assertEqual(m.group(1), must_point_to,
                             f"{alias} 가 {m.group(1)} 을 가리킨다 — "
                             f"{must_point_to} 여야 한다")

    def test_output_on_off_buttons_consume_their_own_token(self):
        """On 버튼은 **언제나** "버튼 켜짐", Off 버튼은 "버튼 꺼짐" 색이다.

        2026-09-08: 예전엔 On 버튼이 "행이 꺼져 있으면 꺼짐색" 으로 칠해졌고,
        이 검사도 그 동작(on 규칙이 output-off 를 읽는 것)을 고정하고 있었다.
        그 탓에 settings/custom_ui 에서 "버튼 켜짐" 을 바꿔도 꺼진 행 —
        즉 대부분의 행 — 에서는 아무 변화가 없었다. 행의 상태는 행 배경
        (bg_on/bg_off)이 이미 말하므로, 버튼은 자기 색을 입는다.
        """
        text = re.sub(r"/\*.*?\*/", "", ENTRY_UI.read_text(encoding="utf-8"),
                      flags=re.S)
        on_body = re.search(r"\.btn\.form-control\.aot-btn-on\s*\{([^}]*)\}",
                            text)
        off_body = re.search(r"\.btn\.form-control\.aot-btn-off\s*\{([^}]*)\}",
                             text)
        self.assertIsNotNone(on_body, ".btn.form-control.aot-btn-on 규칙이 없다")
        self.assertIsNotNone(off_body, ".btn.form-control.aot-btn-off 규칙이 없다")
        self.assertIn("--aot-btn-bg-output-on", on_body.group(1),
                      "On 버튼이 '버튼 켜짐' 색을 읽지 않는다")
        self.assertNotIn("--aot-btn-bg-output-off", on_body.group(1),
                         "On 버튼이 '버튼 꺼짐' 색을 입고 있다 — "
                         "'버튼 켜짐' 설정이 화면에 나타날 수 없게 된다")
        self.assertNotIn("--aot-btn-bg-active", on_body.group(1))
        self.assertIn("--aot-btn-bg-output-off", off_body.group(1))
        self.assertNotIn("--aot-btn-bg-inactive", off_body.group(1))


if __name__ == "__main__":
    unittest.main()
