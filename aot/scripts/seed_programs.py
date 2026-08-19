#!/usr/bin/env python3
"""재배 프로그램 **템플릿 카탈로그** — 사람이 고를 때 꺼내 쓰는 예시.

⚠ **더 이상 내장 프로그램을 미리 깔지 않는다**(2026-08-19 방향 전환). 쓰지도 않는
작물 7종이 목록에 먼저 들어가 있으면, 사용자는 자기 것을 찾기 전에 남의 것을
지나쳐야 한다. AoT 는 농장 전용이 아니라 공원·체육시설·교통시설에도 쓰이므로
"채소 7종" 이 기본값인 것은 특히 좁다.

카탈로그는 **코드 상수**로만 존재하고, 화면의 "템플릿에서 시작" 에서 고를 때
비로소 사용자 프로그램(`source='user'`)으로 만들어진다.

정본: docs/design/program-layer.md

## 두 층 — 카테고리가 먼저, 작물종은 그 아래(2026-08-19)

세부 작물 단위로만 나열하면 목록이 늘어날수록 고르는 부담이 커진다. 그래서
**카테고리(넓은 범주, 예: 과채류)를 먼저 보여주고, 작물종은 "더 구체적으로"
고르는 선택지로 둔다.** 카테고리로 만든 프로그램은 사람이 화면에서 실제 대상에
맞게 고치는 것을 전제로 한다 — `_CATEGORY_MAP` 의 설명을 보라.

**카테고리는 소속 작물이 있어야만 만든다.** 스켈레톤 일수는 소속 작물들의
`STAGE_DURATION_MAP` 값을 통계로 요약한 것이지 새로 지어낸 값이 아니다
(`_category_stages()` 참조).

### 얼마나 만들 수 있나 — 점검 결과(2026-08-19)

카테고리 이름 자체는 `ext_translation_table.CROP_NAME_MAP` 이 이미 5갈래로 나눠
두고 있다(과채류·엽채류·근채류·허브·화훼류 — AI 번역표 용도로 먼저 생겼다).
그런데 **단계·기간 실측 자료(`STAGE_DURATION_MAP`)가 있는 작물은 7종뿐이고,
그 7종이 5갈래 중 단 2갈래(과채류·엽채류)에만 들어 있다.** 나머지 세 갈래는
이름은 있어도 소속 작물이 0종이라 지금은 만들 수 없다:

| 갈래 | `CROP_NAME_MAP` 상 종수 | `STAGE_DURATION_MAP` 상 종수 | 카테고리 |
|------|------------------------|------------------------------|----------|
| 과채류 | 12 (토마토·오이·딸기 등) | 5 | ✅ 지금 만들어진다 |
| 엽채류 | 9 (상추·배추·케일 등) | 2 | ✅ 지금 만들어진다 |
| 근채류 | 4 (무·당근·감자·고구마) | 0 | ⏳ 대표 작물 실측 자료 없음 |
| 허브류 | 6 (바질·파슬리·민트 등) | 0 | ⏳ 동일 |
| 화훼류 | 6 (장미·국화·난 등) | 0 | ⏳ 동일 |

`GeoProgram.kind`(대상 종류) 축으로 한 단계 더 올려 봐도 같다 — `vegetation` 외의
`livestock`·`facility`·`other` 는 이 저장소 어디에도 단계·기간 표가 없다(가축·
시설물 전용 소스가 아직 없다). 그래서 **지금 실제로 만들 수 있는 카테고리는
정확히 2개**이고, 이 스크립트가 만드는 것도 그 2개뿐이다. 나머지는 이름만
예약해 둔다(`_CATEGORY_MAP` 에 있지만 소속이 없어 `catalog()` 가 걸러낸다) —
대표 작물이 `STAGE_DURATION_MAP` 에 추가되면 이 파일은 손댈 것 없이 그 카테고리가
자동으로 생긴다.

### 왜 지금 만드나 — 뒤로 미루는 비용

이 계층은 **DB 에 아무것도 저장하지 않는다** — `catalog()` 는 매번 다시 계산하는
순수 함수라, 나중에 추가해도 마이그레이션이나 기존 데이터 백필이 필요 없다.
그런데도 지금 만드는 이유는 두 가지다:

1. **이름은 지금 정하는 편이 싸다.** 카테고리 이름을 화면에 노출한 뒤 바꾸면
   사용자가 다시 배워야 한다. `CROP_NAME_MAP` 이 이미 쓰는 이름을 그대로 가져다
   쓰면, 나중에 세 번째·네 번째 카테고리가 생겨도 이름을 새로 짓는 일이 없다.
2. **목록은 작물종이 늘수록 나빠진다.** 지금 7종에서 나중에 20~30종으로 늘면
   평면 목록은 그때부터 부담이 되고, 그 시점에 카테고리를 소급 적용하는 것보다
   처음부터 두 층으로 짜 두는 쪽이 항목 하나 늘 때마다의 비용이 낮다.

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

## 목표(`targets`)는 채우지 않는다

`targets` 는 채우지 않는다. 잠깐 광합성 프리셋의 **작물 단위** 값을 모든 단계에
복사했는데, 그것은 **단계별 값이 아니다** — 육묘기와 착과기의 목표가 같을 리 없고,
같은 값을 여러 칸에 채워 두면 사람은 그것을 "조사된 추천값" 으로 읽는다. 채워진
숫자는 빈 칸보다 강한 주장이다(2026-08-19 되돌림). 단계별 목표는 **실제 조사로**
채운다(작물별 재배 지침·시험 자료). 그 전까지는 비워 두고, 사람이 자기 재배
방식대로 적는다. 카테고리 템플릿은 작물종보다도 더 넓은 범위를 뭉뚱그리므로,
목표를 지어낼 근거가 더 약하다 — 마찬가지로 비운다.

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
import statistics
import sys

# 단계 키 → 표시 이름(한국어). 화면 번역은 msgid 로 따로 하고, 여기에는 시드가
# 스스로 읽히도록 기본 이름을 넣는다. **딕셔너리 삽입 순서 = 생육 진행 순서**다 —
# 카테고리 스켈레톤을 정렬할 때 이 순서를 그대로 쓴다(_STAGE_ORDER).
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
_STAGE_ORDER = {key: i for i, key in enumerate(_STAGE_NAMES)}

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

# 카테고리 — 이름은 `ext_translation_table.CROP_NAME_MAP` 이 이미 쓰는 5갈래를
# 그대로 가져온다(새 어휘를 짓지 않는다). **소속이 있어야 만든다** — 근채류·
# 허브류·화훼류는 지금 `STAGE_DURATION_MAP` 에 대표 작물이 하나도 없어 이름만
# 예약해 둔다(catalog() 가 실행 시점에 소속을 걸러낸다 — 여기 있어도 소속이
# 0이면 카탈로그에 나타나지 않는다). 대표 작물이 `STAGE_DURATION_MAP` 에
# 추가되면 이 표에 소속만 적어 넣으면 된다(위 "얼마나 만들 수 있나" 참조).
_CATEGORY_MAP = {
    'fruiting_vegetable': {
        'name': '과채류',
        'members': ['tomato', 'cherry_tomato', 'paprika', 'cucumber', 'strawberry'],
    },
    'leafy_vegetable': {
        'name': '엽채류',
        'members': ['lettuce', 'spinach'],
    },
    'root_vegetable': {'name': '근채류', 'members': []},   # 무·당근·감자·고구마 — 대기
    'herb':           {'name': '허브류', 'members': []},   # 바질·파슬리·민트 등 — 대기
    'ornamental':     {'name': '화훼류', 'members': []},   # 장미·국화·난 등 — 대기
}

# 작물종 → 소속 카테고리 키(역방향 조회, catalog() 가 작물종 항목에 붙인다).
_SPECIES_CATEGORY = {
    m: cat_key for cat_key, cat in _CATEGORY_MAP.items() for m in cat['members']
}


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


def _category_stages(members):
    """소속 작물들의 `STAGE_DURATION_MAP` 을 합쳐 카테고리 스켈레톤을 만든다.

    **여기서 새 값을 지어내지 않는다** — 이미 있는 하드코딩 표를 통계로
    요약할 뿐이다:

    1. 소속 작물마다 단계 길이를 구한다(`_stages_from_cumulative`).
    2. 소속들이 실제로 갖고 있는 단계 키를 합친다(합집합) — 예를 들어 딸기만
       가진 화아분화기도 "과채류" 카테고리에 나타난다.
    3. 단계 순서는 `_STAGE_NAMES` 에 이미 있는 생육 순서로 정렬한다.
    4. 그 단계를 가진 소속들의 길이 **중앙값**을 그 단계의 일수로 쓴다(소속
       하나만 그 단계를 가지면 중앙값은 그 값 그대로다 — 표본이 하나뿐이라는
       뜻이고, 그만큼 대표성이 약하다는 것도 사실이다).
    5. 마지막 단계는 소속 전부가 그렇듯 항상 `days=None`("끝까지")이다.

    **이 값은 대표값이지 정답이 아니다.** 카테고리로 만든 프로그램은 사람이
    화면에서 실제 대상에 맞게 고치는 것을 전제로 한다(그래서 `notes` 에
    그렇게 적어 둔다 — `catalog()` 참조).
    """
    from aot.ai.context.growth_stage_resolver import STAGE_DURATION_MAP

    per_member = {}
    for m in members:
        lengths = {st['key']: st['days']
                  for st in _stages_from_cumulative(STAGE_DURATION_MAP[m])
                  if st['days'] is not None}
        per_member[m] = lengths

    keys = set()
    for lengths in per_member.values():
        keys.update(lengths.keys())
    ordered_keys = sorted(keys, key=lambda k: _STAGE_ORDER.get(k, 999))

    out = []
    for key in ordered_keys:
        lengths = [per_member[m][key] for m in members if key in per_member[m]]
        out.append({
            'key': key,
            'name': _STAGE_NAMES.get(key, key),
            'days': int(round(statistics.median(lengths))),
        })
    # 마지막 단계 — 소속 작물 전부가 "끝까지" 로 끝나므로 카테고리도 그렇다.
    out.append({'key': 'harvest', 'name': _STAGE_NAMES.get('harvest', 'harvest'),
               'days': None})
    return out


def catalog():
    """템플릿 목록 → `[{key, name, subject, kind, scope, stages, …}]`.

    두 층을 이어 붙여 반환한다 — **카테고리가 먼저, 작물종이 그 다음**이다:

    - `scope='category'`: 넓은 범주(과채류 등). `members` 에 소속 작물종 키
      목록을 담아, 화면이 "또는 정확한 작물로 시작" 을 이어 보여줄 수 있게 한다.
      소속이 없는 카테고리(근채류 등, `_CATEGORY_MAP` 참조)는 만들지 않는다.
    - `scope='species'`: 기존의 작물종별 항목. `category` 필드로 소속 카테고리
      키를 담는다(없으면 `None`).

    모든 항목은 `kind='vegetation'` 이다 — 이 카탈로그는 `STAGE_DURATION_MAP`
    (작물 표) 하나만 읽으므로 다른 종류(`GeoProgram.kind` 의 livestock·facility·
    other)를 지어내지 않는다. 소비처는 자기 종류만 고른다는 원칙을 카탈로그
    쪽에서도 그대로 따르는 것 — DB 컬럼 기본값에 기대지 않고 여기서 명시한다.

    출처는 두 하드코딩 표다 — `STAGE_DURATION_MAP`(단계·기간)과
    `_CROP_PRESETS`(광합성 파라미터·권장 목표). **여기서 값을 다시 적지 않는다**:
    두 곳에 적으면 반드시 갈린다. 카테고리의 단계 일수도 이 표를 통계로 요약한
    것이지 새로 적은 값이 아니다(`_category_stages` 참조).

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

    # ── 카테고리 ──────────────────────────────────────────────────────
    # 소속이 하나도 없으면 만들지 않는다 — 근거 없는 스켈레톤은 빈 칸보다 나쁘다.
    for cat_key, cat in _CATEGORY_MAP.items():
        members = [m for m in cat['members'] if m in STAGE_DURATION_MAP]
        if not members:
            continue
        member_names = '·'.join(_CROP_NAMES.get(m, m) for m in members)
        out.append({
            'key': 'cat_%s' % cat_key,
            'name': cat['name'],
            # subject 는 비울 수 없으므로(저장 규칙) 카테고리 이름을 기본값으로
            # 채운다 — 사람이 그 자리에서 실제 대상 이름으로 고쳐 쓴다.
            'subject': cat['name'],
            'kind': 'vegetation',
            'scope': 'category',
            'category': None,
            'members': members,
            'stages': _category_stages(members),
            'photosynthesis': None,
            'notes': ('카테고리 대표값 — %s종(%s)의 단계 일수 중앙값입니다. '
                      '실제 재배 전 단계·일수·목표를 반드시 실제 대상에 맞게 '
                      '고치세요.' % (len(members), member_names)),
        })

    # ── 작물종 ────────────────────────────────────────────────────────
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
            'kind': 'vegetation',
            'scope': 'species',
            'category': _SPECIES_CATEGORY.get(crop),
            'stages': stages,
            'photosynthesis': photo,
            'notes': None,
        })
    return out


def purge_builtin(app):
    """예전 시드가 깔아 둔 `source='builtin'` **식생** 프로그램을 걷어낸다.

    `kind='vegetation'` 으로 좁힌다 — `GeoProgram` 은 가축·시설물과 테이블을
    같이 쓰므로, 종류를 안 걸면 이 시드가 모르는 다른 종류의 내장 프로그램까지
    건드리게 된다.

    **참조 중인 것은 남긴다** — 지우면 그 작기가 "무엇을 목표로 길렀나" 의 근거를
    잃는다(program_io.delete_program 과 같은 규칙).
    """
    from aot.aot_flask.extensions import db
    from aot.databases.models import GeoProgram, GeoPlot

    removed, kept = [], []
    with app.app_context():
        for row in GeoProgram.query.filter_by(source='builtin',
                                               kind='vegetation').all():
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
            cats = [it for it in items if it['scope'] == 'category']
            species = [it for it in items if it['scope'] == 'species']
            print('카테고리 %d 종 + 작물종 %d 종 (DB 에 넣지 않는다 — 화면에서 '
                  '고를 때 만들어진다)' % (len(cats), len(species)))
            for it in cats:
                print('  - [범주] %-20s %s (%d단계, 소속 %d종)'
                      % (it['key'], it['name'], len(it['stages']),
                         len(it['members'])))
            for it in species:
                has_t = any(st.get('targets') for st in it['stages'])
                cat = (' · 소속 %s' % it['category']) if it['category'] else ''
                print('  - %-14s %s (%d단계%s%s)'
                      % (it['key'], it['name'], len(it['stages']),
                         ', 목표 있음' if has_t else '', cat))
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
