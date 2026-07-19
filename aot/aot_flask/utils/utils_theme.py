# coding=utf-8
"""전역 테마 팔레트 헬퍼 (docs/design/color-system.md)

settings/custom_ui 에서 저장한 사용자 색(Misc.custom_theme_json 의
band_1..5 / chart_1..6)을 aot.config 의 기본 팔레트 위에 오버레이해 돌려준다.
위젯(.py)·inject_variables 가 공용으로 사용한다.
"""
import json
import re

from aot.config import (BAND_PALETTE,
                        GRAPH_SERIES_PALETTE,
                        GRAPH_SERIES_PALETTE_DARK)

_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')


def _theme_dict():
    # ORM 대신 Core SELECT: 세션 identity map 의 stale Misc 를 우회해
    # 항상 DB 현재값을 읽는다 (/custom.css 의 expire_all 과 같은 취지).
    try:
        import sqlalchemy as sa
        from aot.aot_flask.extensions import db
        row = db.session.execute(
            sa.text("SELECT custom_theme_json FROM misc LIMIT 1")).first()
        theme = json.loads((row[0] if row else None) or '{}')
        return theme if isinstance(theme, dict) else {}
    except Exception:
        return {}


def _overlay(base, theme, prefix, count):
    out = list(base)
    for i in range(count):
        val = str(theme.get(f'{prefix}_{i + 1}', '')).strip()
        if _COLOR_RE.match(val) and i < len(out):
            out[i] = val
    return out


def get_band_palette():
    """측정 5단계 밴드 팔레트 (사용자 오버레이 적용, 항상 5색)."""
    return _overlay(BAND_PALETTE, _theme_dict(), 'band', 5)


def get_graph_series_palette(dark=False):
    """차트 시리즈 팔레트 (사용자 오버레이는 라이트/다크 공통 앞 6색만)."""
    base = GRAPH_SERIES_PALETTE_DARK if dark else GRAPH_SERIES_PALETTE
    return _overlay(base, _theme_dict(), 'chart', 6)
