#!/usr/bin/env python3
"""재배 프로그램 **템플릿 카탈로그** — 사람이 고를 때 꺼내 쓰는 예시.

⚠ **더 이상 내장 프로그램을 미리 깔지 않는다**(2026-08-19 방향 전환). 쓰지도 않는
작물 7종이 목록에 먼저 들어가 있으면, 사용자는 자기 것을 찾기 전에 남의 것을
지나쳐야 한다. AoT 는 농장 전용이 아니라 공원·체육시설·교통시설에도 쓰이므로
"채소 7종" 이 기본값인 것은 특히 좁다.

카탈로그는 **코드 상수**로만 존재하고, 화면의 "템플릿에서 시작" 에서 고를 때
비로소 사용자 프로그램(`source='user'`)으로 만들어진다.

정본: docs/design/program-layer.md

## 무엇을 옮기는가

- 단계와 기간: `aot/ai/context/growth_stage_resolver.py` 의 `STAGE_DURATION_MAP`
  (RDA 시설재배 지침 기반, 지금은 **AI 만** 읽는다)
- 광합성 파라미터·권장 목표: `aot/scripts/seed_crop_presets.py` 의 `_CROP_PRESETS`
  (지금은 **제어만** 읽는다)

둘은 같은 작물을 말하면서 서로를 모른다. 여기서 한 프로그램으로 합친다.

## 누적일 → 단계 길이

`STAGE_DURATION_MAP` 은 **누적 일수**(그 단계가 끝나는 날)로 적혀 있다. 프로그램의
`days` 는 **그 단계의 길이**다 — 누적으로 두면 중간 단계를 늘릴 때 뒤 단계를 전부
손봐야 한다. 여기서 차분으로 변환한다.

마지막 단계의 `999` 는 "끝까지" 라는 뜻이라 길이로 옮기지 않는다(`days=None`).
수확기는 사람이 끝낼 때까지다.

## 목표도 함께 채운다

`targets` 는 프리셋의 **작물 단위** 값이라 모든 단계에 같은 값이 들어간다. 그래도
빈 칸보다 낫다 — 사람이 그 자리에서 단계별로 고치면 된다. 프리셋에 없는 항목(야간
온도·습도)은 **지어내지 않고 비운다.**

## `--purge-builtin`

예전 버전이 깔아 둔 내장 프로그램을 걷어낸다. **참조 중인 것은 남긴다** — 지우면
그 작기가 "무엇을 목표로 길렀나" 의 근거를 잃는다.

사용:
    python3 -m aot.scripts.seed_programs --list     # 카탈로그 보기
    python3 -m aot.scripts.seed_programs --purge-builtin
        # 예전에 깔린 내장 프로그램을 걷어낸다(참조 중인 것은 남긴다)

종료 코드 0 = 정상, 2 = 실패.
"""
import argparse
import json
import sys

# 단계 키 → 표시 이름(한국어). 화면 번역은 msgid 로 따로 하고, 여기에는 시드가
# 스스로 읽히도록 기본 이름을 넣는다.
_STAGE_NAMES = {
    'seedling':        '육묘기',
    'germination':     '발아기',
    'sowing':          '파종기',
    'transplant':   '정식기',
    'vegetative':      '영양생장기',
    'vegetative_early': '초기생장',
    'vegetative_late': '후기생장',
    'flower_initiation': '화아분화기',
    'flowering':       '개화기',
    'fruit_set':       '착과기',
    'fruit_development': '비대기',
    'fruiting':        '결실기',
    'runner':          '런너기',
    'pre_harvest':     '수확전기',
    'harvest':         '수확기',
    'post_harvest':    '수확후기',
}

_CROP_NAMES = {
    'tomato':        '토마토',
    'cherry_tomato': '방울토마토',
    'paprika':       '파프리카',
    'cucumber':      '오이',
    'strawberry':    '딸기',
    'lettuce':       '상추',
    'spinach':       '시금치',
}

# 광합성 프리셋의 작물 키가 다른 경우의 대응(파프리카 = pepper 프리셋).
_PRESET_ALIAS = {'paprika': 'pepper', 'cherry_tomato': 'tomato'}


def _stages_from_cumulative(pairs):
    """[(key, 누적일), …] → [{key, name, days}] (days = 그 단계의 길이)."""
    out, prev = [], 0
    for key, cum in pairs:
        if cum >= 999:
            days = None            # 끝까지 — 사람이 끝낸다
        else:
            days = max(int(cum) - prev, 0)
            prev = int(cum)
        out.append({
            'key': key,
            'name': _STAGE_NAMES.get(key, key),
            'days': days,
            # P1 은 단계·기간까지다. 목표·자원·GDD 는 이후 단계에서 채운다 —
            # 빈 dict 를 넣어 두면 화면이 "있는데 비었다" 로 읽는다.
        })
    return out


def catalog():
    """템플릿 목록 → `[{key, name, subject, stages, photosynthesis}]`.

    출처는 두 하드코딩 표다 — `STAGE_DURATION_MAP`(단계·기간)과
    `_CROP_PRESETS`(광합성 파라미터·권장 목표). **여기서 값을 다시 적지 않는다**:
    두 곳에 적으면 반드시 갈린다.

    ⚠ **목표(`targets`)는 채우지 않는다** (2026-08-19 되돌림). 잠깐 광합성 프리셋의
    작물 단위 값을 모든 단계에 복사했는데, 그것은 **단계별 값이 아니다** — 육묘기와
    착과기의 목표가 같을 리 없고, 같은 값을 여섯 칸에 채워 두면 사람은 그것을
    "조사된 추천값" 으로 읽는다. 채워진 숫자는 빈 칸보다 강한 주장이다.

    단계별 목표는 **실제 조사로** 채운다(작물별 재배 지침·시험 자료). 그 전까지는
    비워 두고, 사람이 자기 재배 방식대로 적는다.
    """
    from aot.ai.context.growth_stage_resolver import STAGE_DURATION_MAP
    try:
        from aot.scripts.seed_crop_presets import _CROP_PRESETS
    except Exception:
        _CROP_PRESETS = {}

    out = []
    for crop, pairs in STAGE_DURATION_MAP.items():
        if crop.startswith('_'):
            continue
        preset = _CROP_PRESETS.get(_PRESET_ALIAS.get(crop, crop)) or {}
        stages = _stages_from_cumulative(pairs)

        # 목표는 비워 둔다(위 docstring). 광합성 파라미터는 **작물 단위 모델
        # 상수**라 단계와 무관하므로 그대로 싣는다 — 그쪽은 채워도 거짓이 아니다.
        photo = {k: v for k, v in preset.items()
                 if k not in ('display_name', 'notes')} or None
        out.append({
            'key': crop,
            'name': _CROP_NAMES.get(crop, crop),
            'subject': crop,
            'stages': stages,
            'photosynthesis': photo,
        })
    return out


def purge_builtin(app):
    """예전 시드가 깔아 둔 `source='builtin'` 프로그램을 걷어낸다.

    **참조 중인 것은 남긴다** — 지우면 그 작기가 "무엇을 목표로 길렀나" 의 근거를
    잃는다(program_io.delete_program 과 같은 규칙).
    """
    from aot.aot_flask.extensions import db
    from aot.databases.models import GeoProgram, GeoPlot

    removed, kept = [], []
    with app.app_context():
        for row in GeoProgram.query.filter_by(source='builtin').all():
            used = GeoPlot.query.filter_by(program_uuid=row.unique_id).count()
            if used:
                kept.append((row.name, used))
                continue
            removed.append(row.name)
            db.session.delete(row)
        db.session.commit()
    return removed, kept


def main():
    ap = argparse.ArgumentParser(description='재배 프로그램 템플릿 카탈로그')
    ap.add_argument('--list', action='store_true', help='카탈로그 보기')
    ap.add_argument('--purge-builtin', action='store_true',
                    help='예전에 깔린 내장 프로그램 제거(참조 중인 것은 남김)')
    ap.add_argument('--json', action='store_true', help='기계 판독')
    args = ap.parse_args()

    if args.list or not args.purge_builtin:
        items = catalog()
        if args.json:
            print(json.dumps(items, ensure_ascii=False))
        else:
            print('템플릿 %d 종 (DB 에 넣지 않는다 — 화면에서 고를 때 만들어진다)'
                  % len(items))
            for it in items:
                has_t = any(st.get('targets') for st in it['stages'])
                print('  - %-14s %s (%d단계%s)'
                      % (it['key'], it['name'], len(it['stages']),
                         ', 목표 있음' if has_t else ''))
        if not args.purge_builtin:
            return 0

    try:
        from aot.start_flask_ui import app
    except Exception as exc:                       # pragma: no cover
        print('앱 로드 실패: %s' % exc, file=sys.stderr)
        return 2
    try:
        removed, kept = purge_builtin(app)
    except Exception as exc:
        print('정리 실패: %s' % exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({'removed': removed,
                          'kept_in_use': [{'name': n, 'plots': c}
                                          for n, c in kept]}, ensure_ascii=False))
    else:
        print('제거 %d · 사용 중이라 남김 %d' % (len(removed), len(kept)))
        for n in removed:
            print('  - %s' % n)
        for n, c in kept:
            print('  ! %s (구획 %d 건이 사용 중)' % (n, c))
    return 0


if __name__ == '__main__':
    sys.exit(main())
