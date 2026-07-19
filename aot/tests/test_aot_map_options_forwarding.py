# coding=utf-8
"""AoT_map custom_options 전달(forwarding) 회귀 가드.

배경:
    위젯 JS는 모든 custom_option을 `vars.vars`(= maps.py
    `generate_page_variables_logic()`가 반환하는 widget_vars 딕셔너리)에서 읽는다.
    과거 widget_vars가 손으로 유지하는 화이트리스트였던 탓에, 새로 추가된 옵션
    (sensor_label_*, facility_render_mode, enable_3d_terrain, popup_default_tab …)이
    저장은 되지만 클라이언트로 전달되지 않아 항상 JS 기본값으로 동작하는 버그가 있었다.

    근본 수정은 widget_vars 를 raw widget_options 위에 덮어쓰는 pass-through 병합으로
    전환한 것이다. 이 테스트는 그 병합이 사라져 다시 화이트리스트로 회귀하는 것을 막는다.

    무거운 앱/DB 컨텍스트 없이 돌도록 소스 정적 분석만 사용한다.
"""
import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WIDGET = REPO / "aot" / "aot_flask" / "widgets" / "AoT_map.py"
if not WIDGET.exists():
    WIDGET = REPO / "aot" / "widgets" / "AoT_map.py"
MAPS = REPO / "aot" / "aot_flask" / "geo" / "widget" / "maps.py"


def _custom_option_ids():
    """AoT_map.py WIDGET_INFORMATION['custom_options'] 의 모든 옵션 id 추출."""
    tree = ast.parse(WIDGET.read_text())
    ids = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "id" and isinstance(v, ast.Constant):
                ids.append(v.value)
    return ids


def test_options_extracted():
    ids = _custom_option_ids()
    # 최소한의 대표 옵션이 존재해야 한다 (파서가 깨지지 않았는지 확인).
    assert "sensor_label_style" in ids
    assert "facility_render_mode" in ids
    assert "period" in ids


def test_label_master_toggle():
    """라벨 가시성은 단일 마스터 토글로 통합됨. 개별 카테고리 토글이 되살아나면
    지도 컨트롤러와의 중복이 재발하므로 가드한다."""
    ids = _custom_option_ids()
    assert "show_labels" in ids, "마스터 라벨 토글 show_labels 가 사라졌다."
    for legacy in ("show_site_label", "show_zone_label",
                   "show_device_labels", "show_sensor_labels"):
        assert legacy not in ids, (
            f"{legacy} 는 마스터 show_labels 로 통합되어 제거됐다. "
            "세부 가시성은 지도 컨트롤러(label_hidden_input/output/function)가 담당."
        )
    # maps.py 가 마스터에서 카테고리 게이트를 파생하는지 확인.
    src = MAPS.read_text()
    assert "show_sensor_labels" in src and "show_labels" in src, (
        "maps.py 가 show_labels 마스터에서 게이트(show_sensor_labels 등)를 "
        "파생하지 않는다 — 마스터 토글이 센서 라벨에 도달하지 않음."
    )


def test_passthrough_merge_present():
    """maps.py 가 raw widget_options 를 베이스로 깔고 widget_vars 로 덮어쓰는지 확인.

    이 패턴이 사라지면 신규 옵션이 클라이언트로 전달되지 않는 회귀가 재발한다.
    """
    src = MAPS.read_text()
    assert re.search(r"merged\s*=\s*dict\(widget_options\)", src), (
        "maps.py 의 pass-through 병합(merged = dict(widget_options))이 사라졌다 — "
        "신규 custom_option 이 클라이언트로 전달되지 않는 회귀 위험."
    )
    assert re.search(r"merged\.update\(widget_vars\)", src), (
        "maps.py 의 widget_vars 우선 병합(merged.update(widget_vars))이 사라졌다."
    )


def test_dead_options_removed():
    """소비처가 없어 제거한 옵션이 되살아나지 않도록 가드."""
    ids = _custom_option_ids()
    # enable_3d_controls: pitch/bearing 슬라이더 미구현(렌더 코드 전무)으로 제거됨.
    assert "enable_3d_controls" not in ids, (
        "enable_3d_controls 는 소비처가 없는 죽은 옵션이라 제거되었다. "
        "재도입하려면 실제 3D 컨트롤 렌더 로직을 함께 배선할 것."
    )
