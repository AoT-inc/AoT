# coding=utf-8
"""settings/custom_ui 레거시 별칭이 **자기 필드**의 정본 토큰을 가리키는지
전수 대조한다.

2026-09-08 사고의 일반형. `aot-theme-variables.css` 는 각 레거시 이름을
`--이름: var(--aot-정본);` 으로 정의하고, `routes_general.py` 의 `var_map`
은 각 설정 필드가 `[레거시 이름들..., --aot-정본들...]` 을 함께 발행한다고
선언한다. 이 둘은 **같은 사실을 두 곳에서** 말하고 있어야 한다 — 별칭
정의가 가리키는 `--aot-*` 가, 그 별칭을 발행하는 필드가 var_map 에서
실제로 발행한다고 적어 둔 `--aot-*` 목록 안에 있어야 한다.

실제로 한 번 어긋났다: `bg_btn_on`("버튼 켜짐" — 출력 행 ON 버튼) 이 발행
하는 레거시 이름 `--bg-btn-on` 의 정의가, 전혀 다른 필드
`btn_primary_bg`("주 버튼 배경" — 전역 버튼)의 정본 `--aot-btn-bg-active`
를 가리키고 있었다. 두 필드 기본값이 우연히 같아(#13261B) 화면으로는
드러나지 않았고, 사용자가 "버튼 켜짐" 만 바꿔 봐야만 드러났다.

docs/design/color-system.md §5-13.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROUTES = REPO / "aot" / "aot_flask" / "routes_general.py"
THEME_VARS = REPO / "aot" / "aot_flask" / "static" / "css" / "aot-theme-variables.css"


def _var_map():
    text = ROUTES.read_text(encoding="utf-8")
    m = re.search(r"var_map = \{(.*?)\n        \}", text, re.S)
    assert m, "routes_general.py 에서 var_map 을 못 찾았다 — 구조가 바뀌었다"
    body = m.group(1)
    field_legacy, field_aot, alias_to_fields = {}, {}, {}
    for field, toks in re.findall(r"'([a-z_]+)':\s*\[([^\]]+)\]", body):
        tokens = [t.strip().strip("'\"") for t in toks.split(",")]
        legacy = [t for t in tokens if t.startswith("--") and not t.startswith("--aot-")]
        aot = [t for t in tokens if t.startswith("--aot-")]
        field_legacy[field] = legacy
        field_aot[field] = aot
        for alias in legacy:
            alias_to_fields.setdefault(alias, []).append(field)
    assert field_aot, "var_map 파싱 결과가 비었다 — 정규식이 형식 변화를 못 따라갔다"
    return field_aot, alias_to_fields


def _alias_definitions():
    text = THEME_VARS.read_text(encoding="utf-8")
    defs = re.findall(r"(--[a-z][a-z0-9-]*)\s*:\s*var\((--aot-[a-z0-9-]+)\)\s*;", text)
    assert defs, "aot-theme-variables.css 에서 레거시 별칭 정의를 못 찾았다"
    return defs


class CustomUIAliasTargetMatchesFieldTest(unittest.TestCase):
    def test_every_alias_points_at_its_own_fields_canonical_token(self):
        field_aot, alias_to_fields = _var_map()
        mismatches = []
        for alias, canonical in _alias_definitions():
            for field in alias_to_fields.get(alias, []):
                if canonical not in field_aot.get(field, []):
                    mismatches.append(
                        f"{alias} -> {canonical} (정의), 그런데 이 별칭을 "
                        f"발행하는 var_map['{field}'] 는 {field_aot.get(field)} "
                        f"만 발행한다 — {canonical} 는 다른 필드 것일 수 있다")
        assert not mismatches, (
            "레거시 별칭이 자기 필드가 아닌 다른 필드의 정본을 가리킨다 "
            "(settings/custom_ui 값을 바꿔도 반영 안 되는 원인): "
            + " | ".join(mismatches[:5]))


if __name__ == "__main__":
    unittest.main()
