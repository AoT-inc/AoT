#!/usr/bin/env python3
"""지도 데이터 쓰기 소유권 검사기 — geo 패키지 밖의 GeoShape 쓰기를 거부한다.

지도 데이터는 geo 패키지가 소유한다. 장치·AI·위젯 등 다른 도메인의 로직이
GeoShape 를 직접 만들거나 지우면, 그 도메인이 지도의 불변식(타입 어휘,
채널 정규화, aot_type 미저장, 마커 유일성, 시설 연쇄)을 전부 알아야 하고
결국 아무도 다 알지 못한다. 2026-08-03 오염 사고의 구조적 원인이 이것이었다
— AI 대량생성이 channel_id 없이 마커를 직접 INSERT 했고, 장치 삭제 경로가
지도 구조를 통째로 지웠다.

DB 트리거(p6_22/p6_23)가 '잘못된 데이터'를 막는다면, 이 검사기는 '규칙을
모르는 코드'를 막는다. 트리거는 런타임에 터지지만 이건 커밋/CI 시점에
터진다 — 실패를 왼쪽으로 옮긴다.

규칙:
  - GeoShape/GeoFacility 쓰기(생성·삭제·bulk delete)와 geo_shape 원시 SQL 은
    ALLOWED_PREFIXES 안에서만 허용한다.
  - [GB-6] 사망 선고된 `GeoShape.device_id`/`channel_id` 를 새로 참조하지
    않는다. 남은 사용처는 LEGACY_COLUMN_USERS 에 고정돼 있고, 그 명부는
    허가 목록이 아니라 "아직 옮기지 못한 것"의 목록이다 — 비어야 끝난다.
  - 그 밖의 모듈은 geo 패키지의 공개 함수를 쓴다:
      장치 배치      aot.aot_flask.geo.device_placement.place_device
      배치 해제      aot.aot_flask.geo.device_placement.unplace_device
      소속 조회      aot.space.device_membership
      도형 저장      aot.aot_flask.geo.geo_overlays.GeoOverlayManager

새 위반을 추가하지 말 것. 기존 예외를 늘려야 한다면 그 모듈이 정말 지도
데이터의 소유자인지 먼저 따질 것.

사용:
    python3 aot/scripts/check_geo_writes.py           # 전체 검사
    python3 aot/scripts/check_geo_writes.py --list    # 허용 경로 출력

종료 코드 0 = 위반 없음, 1 = 위반 발견.

@phase active
@stability stable
"""
import argparse
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SCAN_ROOT = os.path.join(ROOT, 'aot')

# 지도 데이터를 소유하는 모듈들(저장소 루트 기준, '/' 구분).
ALLOWED_PREFIXES = (
    'aot/aot_flask/geo/',              # geo 패키지 전체 — 정당한 소유자
    'aot/space/',                      # geo 패키지에서 옮긴 공간 도메인(아키텍처 3단계·4c)
    'aot/aot_flask/api/geo.py',        # geo REST 리소스
    'aot/aot_flask/routes_geo.py',     # geo 페이지·API 라우트(핵심 — blueprint·전역 훅)
    'aot/aot_flask/routes_geo_map.py', # routes_geo 형제 — GeoSetting·parcel·site_order·design
    'aot/aot_flask/cli_geo.py',        # geo 스키마 마이그레이션 CLI
    'aot/databases/',                  # 모델 정의·DDL
    'aot/scripts/',                    # 진단·점검 스크립트
    'aot/tests/',                      # 테스트
)

# 예외 없음 — Phase C(2026-08-08)에서 비웠다.
#
# 여기 있던 3파일(utils_input·utils_output·tab_service)은 장치를 지울 때
# `GeoShape.query.filter(device_id==...).delete()` 로 도형을 직삭제했다.
# 그 코드는 사라졌고 전부 `device_binding.end_all_for_device()` 를 지나간다
# — 원래 목표가 게이트웨이 이관이었고, 이제 달성됐다.
#
# **다시 채우지 말 것.** 장치 삭제 진입점은 17곳이고, 예외를 하나 열면
# 나머지 16곳도 각자 정리하기 시작한다. 그 상태가 정확히 "정책은 6갈래인데
# 실제로 도형을 건드리는 곳은 4곳뿐"이던 시절이다.
GRANDFATHERED = set()

# 쓰기로 간주하는 호출. 읽기(query/filter_by/all/first)는 대상이 아니다 —
# 읽기는 오염을 만들지 않고, 막으면 정당한 조회까지 마비된다.
#
# [GB-7] GeoBinding 포함: 공간↔장치 연결의 정본이므로 GeoShape 와 같은
# 소유권 규칙을 받는다. 장치 삭제 경로 17곳이 각자 바인딩을 종료시키기
# 시작하면 "슬롯당 현재 1개"·"종료는 valid_to 기록" 같은 규칙을 열일곱 벌
# 구현하게 되고, 그 중 하나만 빠뜨려도 조용히 고아가 생긴다 — 도형이
# 정확히 그렇게 썩었다. 밖에서는 geo 패키지의 게이트웨이를 쓴다.
WRITE_CLASSES = ('GeoShape', 'GeoFacility', 'GeoBinding')

# [GB-6] 사망 선고된 컬럼 — 공간↔장치 연결의 정본은 geo_binding 이다.
#
# `GeoShape.device_id`/`channel_id` 는 map_overlay_id 와 같은 절차를 밟는다:
# 신규 참조 금지 → 남은 참조를 전부 리졸버로 옮김 → 마이그레이션에서 컬럼 제거.
# 지금 단계는 첫 번째다. **아래 명부는 "아직 남아 있는 사용처"이지 허가
# 목록이 아니다** — Phase C 가 끝나면 비어야 한다. 늘리지 말 것.
#
# 컬럼을 그냥 두면 죽지 않는다. map_overlay_id 가 그랬다: 사망 선고를 하고도
# 새 코드가 계속 읽고 써서, 결국 복제·zone 재생성·도형 삭제가 참조를 끊는
# 사고로 돌아왔다. 명부를 고정해야 "줄어들고 있는가"를 볼 수 있다.
LEGACY_COLUMN_ATTRS = ('device_id', 'channel_id')
LEGACY_COLUMN_USERS = {
    # geo 패키지 — 폴백 읽기와 마커 경로. 폴백 제거와 함께 사라진다.
    'aot/space/device_binding.py',
    'aot/space/device_membership.py',
    'aot/aot_flask/geo/device_placement.py',
    'aot/aot_flask/geo/geo_overlays.py',
    # 지도 데이터를 만드는 쪽 — 마커 좌표 수집(collect_devices).
    'aot/aot_flask/utils/utils_geo.py',
    # 진단·이행 도구. 레거시를 봐야 하는 것이 존재 이유라 마지막까지 남는다.
    'aot/scripts/backfill_geo_binding.py',
    'aot/scripts/check_geo_integrity.py',
    'aot/scripts/fix_geo_theme_drift.py',
    # geo 밖 소비처는 2026-08-08 에 전부 리졸버(`shapes_for_device`)로
    # 옮겼다 — 이름 동기화·시간대 상속·AI 좌표 동기화·위성 좌표 폴백·조율기
    # 프로필 적재 다섯 곳. 남은 것은 geo 패키지 자신과 진단 도구뿐이다.
}

# geo_shape 를 건드리는 원시 SQL 문자열.
RAW_SQL = re.compile(r'\bgeo_shape\b', re.I)

# db.session.delete(x) 에서 지도 도형으로 의심되는 인자 이름.
DELETE_ARG_HINT = re.compile(r'(?:^|_)(shape|marker|overlay|facility)s?$', re.I)


def _rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, '/')


def _allowed(rel):
    if rel in GRANDFATHERED:
        return True
    return any(rel.startswith(p) for p in ALLOWED_PREFIXES)


def iter_py():
    for dirpath, dirnames, filenames in os.walk(SCAN_ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in ('__pycache__', 'node_modules', 'env')]
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


class _Visitor(ast.NodeVisitor):
    """AST 로 쓰기 호출만 잡는다 — 주석·독스트링·문자열은 원천 제외."""

    def __init__(self):
        self.hits = []          # (lineno, label)

    def visit_Call(self, node):
        f = node.func
        # GeoShape(...) / GeoFacility(...) 직접 생성
        if isinstance(f, ast.Name) and f.id in WRITE_CLASSES:
            self.hits.append((node.lineno, '%s 직접 생성' % f.id))
        elif isinstance(f, ast.Attribute):
            # <...>.delete(...) — GeoShape.query 체인이면 bulk delete
            if f.attr == 'delete':
                src = ast.dump(f.value)
                if any(("id='%s'" % c) in src for c in WRITE_CLASSES):
                    self.hits.append((node.lineno, 'GeoShape bulk delete'))
                elif src.count("attr='delete'") == 0 and \
                        "attr='session'" in src or "id='session'" in src:
                    # db.session.delete(x) — 인자 이름으로 도형 여부 추정
                    arg = node.args[0] if node.args else None
                    nm = getattr(arg, 'id', None) or getattr(arg, 'attr', None)
                    if nm and DELETE_ARG_HINT.search(nm):
                        self.hits.append((node.lineno, 'GeoShape 삭제'))
            # execute(text("... geo_shape ...")) 류
            elif f.attr in ('execute', 'text'):
                for a in node.args:
                    if isinstance(a, ast.Constant) and \
                            isinstance(a.value, str) and RAW_SQL.search(a.value):
                        self.hits.append((node.lineno, 'geo_shape 원시 SQL'))
        self.generic_visit(node)


def scan():
    violations = []
    for path in iter_py():
        rel = _rel(path)
        if _allowed(rel):
            continue
        try:
            text = open(path, encoding='utf-8').read()
            tree = ast.parse(text)
        except Exception:
            continue
        v = _Visitor()
        v.visit(tree)
        if not v.hits:
            continue
        lines = text.splitlines()
        for lineno, label in v.hits:
            snippet = lines[lineno - 1].strip()[:90] if lineno <= len(lines) else ''
            violations.append((rel, lineno, label, snippet))
    return violations


def scan_legacy_columns():
    """[GB-6] `GeoShape.device_id`/`channel_id` 를 새로 쓰는 파일을 찾는다.

    세 가지 패턴을 본다: 클래스 속성 참조(`GeoShape.device_id`), 생성자 인자
    (`GeoShape(device_id=...)`), 질의 인자(`GeoShape.query.filter_by(
    device_id=...)`). 실제로 새 사용처가 생기는 모양이 이 셋이다.

    **놓치는 것이 하나 있다**: 이미 손에 든 도형 인스턴스에 대한 대입
    (`row.device_id = x`). 그걸 잡으려면 변수의 타입을 알아야 하는데, 이름만
    보고 잡으면 Input/Output 의 동명 컬럼까지 전부 걸려 신호가 소음에
    묻힌다. 그 구멍은 `check_geo_integrity` 의 binding-drift 가 결과 쪽에서
    메운다 — 컬럼에만 쓰고 바인딩에 안 쓰면 드리프트가 는다.

    테스트는 대상에서 뺀다. 사망 컬럼이 실제로 죽었는지 확인하는 테스트가
    그 컬럼을 참조하는 것은 정상이다.
    """
    new_users = []
    seen_users = set()
    for path in iter_py():
        rel = _rel(path)
        if rel.startswith('aot/tests/'):
            continue
        if rel in LEGACY_COLUMN_USERS:
            # 명부에 있는 파일이 아직 실제로 쓰는지 확인한다 — 안 쓰면
            # 유령 항목이고, 그대로 두면 명부가 줄어드는 걸 볼 수 없다.
            try:
                body = open(path, encoding='utf-8').read()
                if any(a in body for a in LEGACY_COLUMN_ATTRS) \
                        and 'GeoShape' in body:
                    seen_users.add(rel)
            except Exception:
                seen_users.add(rel)
            continue
        try:
            text = open(path, encoding='utf-8').read()
            tree = ast.parse(text)
        except Exception:
            continue
        lines = text.splitlines()

        def _hit(node):
            snippet = (lines[node.lineno - 1].strip()[:90]
                       if node.lineno <= len(lines) else '')
            new_users.append((rel, node.lineno, snippet))

        for node in ast.walk(tree):
            # ① GeoShape.device_id — 클래스 속성 참조(비교·정렬·with_entities)
            if isinstance(node, ast.Attribute) \
                    and node.attr in LEGACY_COLUMN_ATTRS \
                    and isinstance(node.value, ast.Name) \
                    and node.value.id == 'GeoShape':
                _hit(node)
                continue
            if not isinstance(node, ast.Call):
                continue
            # ② GeoShape(device_id=...) — 생성자 인자
            if isinstance(node.func, ast.Name) and node.func.id == 'GeoShape':
                if any(k.arg in LEGACY_COLUMN_ATTRS for k in node.keywords):
                    _hit(node)
                continue
            # ③ GeoShape.query...filter_by(device_id=...) — 가장 흔한 신규 사용
            if isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ('filter_by', 'update') \
                    and "id='GeoShape'" in ast.dump(node.func.value):
                if any(k.arg in LEGACY_COLUMN_ATTRS for k in node.keywords):
                    _hit(node)
    ghosts = sorted(LEGACY_COLUMN_USERS - seen_users)
    return new_users, ghosts


# [L2] 장치 행의 위치 컬럼 쓰기 금지 — 위치의 정본은 배치(마커 + geo_binding)이고
# 읽는 쪽은 device_location.locate 다. 장치 모델(Input·Output·PID·Trigger·
# Conditional·CustomController·Function)의 latitude/longitude/timezone 에
# 대입하면 두 번째 정본이 생긴다. 컬럼 삭제는 L3·L4.
# 면제는 "장치가 아닌 모델"과 geo 소유 모듈, 그리고 L3 에서 사라질 아래 2건뿐이다.
# **늘리지 말 것.**
#   - twin_config.py: 예보 지점 입력은 지도에 놓지 않는 임의 좌표라 배치가 없다.
#     컬럼이 유일한 저장소(legacy_column 폴백) — L3 에서 지점 전용 자리를 정한 뒤 제거.
#   - device_tz.py: 신규 장치의 시스템 시간대 폴백(tz_source='system') — L4 승격 뒤 제거.
# 장치가 아닌 모델의 timezone 컬럼을 쓰는 파일(사용자·Misc 시간대 설정). 장치 행 쓰기가
# 섞이면 안 되는 파일이므로 늘리지 말 것.
DEVICE_COLUMN_NON_DEVICE_FILES = {
    'aot/aot_flask/utils/utils_settings.py',
}
DEVICE_COLUMN_TRANSITIONAL = {
    'aot/utils/twin_config.py',
    'aot/utils/device_tz.py',
}
DEVICE_COLUMN_ATTRS = ('latitude', 'longitude', 'timezone')
DEVICE_COLUMN_EXEMPT_PREFIXES = (
    'aot/aot_flask/geo/', 'aot/space/',     # geo 소유 모듈(공간 도메인으로 옮긴 것 포함, 아키텍처 4c)
    'aot/databases/', 'aot/scripts/', 'aot/tests/')
# 변수 이름으로는 모델 종류를 알 수 없다(타입 추적 불가) — 면제는 이름이 아니라
# 파일 단위 명부(DEVICE_COLUMN_NON_DEVICE_FILES)로만 한다.


def scan_device_columns():
    """장치 행 위치 컬럼 대입을 찾는다. (rel, lineno, snippet) 목록."""
    hits = []
    for path in iter_py():
        rel = _rel(path)
        if rel.startswith(DEVICE_COLUMN_EXEMPT_PREFIXES) \
                or rel in DEVICE_COLUMN_TRANSITIONAL \
                or rel in DEVICE_COLUMN_NON_DEVICE_FILES:
            continue
        try:
            text = open(path, encoding='utf-8').read()
            tree = ast.parse(text)
        except Exception:
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            else:
                continue
            flat = []
            for t in targets:
                flat.extend(t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])
            for t in flat:
                if isinstance(t, ast.Attribute) and t.attr in DEVICE_COLUMN_ATTRS \
                        and isinstance(t.value, ast.Name) \
                        and t.value.id not in ('self', 'cls'):
                    hits.append((rel, node.lineno,
                                 lines[node.lineno - 1].strip()[:90]))
    return hits


# [L3] 장치 행의 죽은 컬럼 3개 — 앱 코드는 읽지도 쓰지도 않는다. 위치는 배치가
# 정본이고(device_location.locate / device_membership.map_for_device), 컬럼 정의·DDL
# 은 다음 PR 에서 걷어낸다. 속성 접근(읽기·쓰기, self/cls 포함)·getattr·키워드 인자
# (filter_by/모델 생성자)만 잡는다 — dict 키·문자열은 보지 않으므로, 다른 뜻의
# `location_source`(실외 분류 출처, 구획 도형 출처)는 dict 키라 걸리지 않는다.
DEAD_DEVICE_COLUMNS = ('map_config_id', 'location_source', 'location_updated_utc')
DEAD_COLUMN_EXEMPT_PREFIXES = (
    'aot/databases/', 'aot/tests/', 'alembic_db/', 'aot/alembic', 'migrations/')
# 줄 단위 예외 명부 {(rel, 소스 줄 일부): 사유}. 비어 있어야 정상이다.
DEAD_COLUMN_ALLOWLIST = {}


def scan_dead_device_columns(root=None):
    """죽은 장치 컬럼 3개를 다루는 코드를 찾는다. (rel, lineno, snippet) 목록."""
    hits = []
    for path in iter_py():
        rel = _rel(path)
        if rel.startswith(DEAD_COLUMN_EXEMPT_PREFIXES):
            continue
        try:
            text = open(path, encoding='utf-8').read()
            tree = ast.parse(text)
        except Exception:
            continue
        lines = text.splitlines()
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in DEAD_DEVICE_COLUMNS:
                found.append(node.lineno)
            elif isinstance(node, ast.Call):
                fn = node.func
                fname = (fn.id if isinstance(fn, ast.Name)
                         else fn.attr if isinstance(fn, ast.Attribute) else '')
                if (fname in ('getattr', 'setattr', 'hasattr')
                        and len(node.args) >= 2
                        and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value in DEAD_DEVICE_COLUMNS):
                    found.append(node.lineno)
                # 키워드 인자는 질의·모델 생성자일 때만 — render_template(map_config_id=…)
                # 같은 템플릿 컨텍스트 변수는 컬럼이 아니다.
                if fname == 'filter_by' or fname[:1].isupper():
                    for kw in node.keywords:
                        if kw.arg in DEAD_DEVICE_COLUMNS:
                            found.append(getattr(kw.value, 'lineno', node.lineno))
        for lineno in sorted(set(found)):
            snippet = lines[lineno - 1].strip()[:90]
            if any(r == rel and frag in snippet
                   for (r, frag) in DEAD_COLUMN_ALLOWLIST):
                continue
            hits.append((rel, lineno, snippet))
    return hits


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true',
                    help='허용 경로를 출력하고 종료')
    args = ap.parse_args()

    if args.list:
        print('소유 모듈(쓰기 허용):')
        for p in ALLOWED_PREFIXES:
            print('  ', p)
        print('예외(정리 예정):')
        for p in sorted(GRANDFATHERED) or ['  (없음)']:
            print('  ', p)
        print('[GB-6] 레거시 컬럼이 아직 남은 파일:')
        for p in sorted(LEGACY_COLUMN_USERS):
            print('  ', p)
        return 0

    violations = scan()
    legacy, ghosts = scan_legacy_columns()
    dev_cols = scan_device_columns()
    dead_cols = scan_dead_device_columns()
    if dead_cols:
        print('FAIL: [L3] 장치 행의 죽은 컬럼(map_config_id/location_source/'
              'location_updated_utc)을 읽거나 씁니다 — %d건\n' % len(dead_cols))
        for rel, lineno, snippet in dead_cols:
            print('  %s:%d' % (rel, lineno))
            print('      %s' % snippet)
        print('\n위치는 device_location.locate / 지도는 device_membership.map_for_device'
              ' 를 쓰세요. 컬럼 정의는 다음 PR 에서 삭제됩니다.\n')
    if dev_cols:
        print('FAIL: [L2] 장치 행의 latitude/longitude/timezone 에 대입합니다 — %d건\n'
              % len(dev_cols))
        for rel, lineno, snippet in dev_cols:
            print('  %s:%d' % (rel, lineno))
            print('      %s' % snippet)
        print('\n위치는 배치가 정본입니다: aot.aot_flask.geo.device_placement.place_device'
              ' / 읽기는 device_location.locate. 컬럼 삭제는 L3·L4.\n')

    if not violations and not legacy and not ghosts and not dev_cols \
            and not dead_cols:
        print('OK: geo 패키지 밖의 지도 데이터 쓰기 없음. '
              'GeoShape.device_id 신규 참조 없음.')
        return 0

    if legacy:
        print('FAIL: [GB-6] 사망 선고된 컬럼을 새로 참조합니다 — %d건\n'
              % len(legacy))
        for rel, lineno, snippet in legacy:
            print('  %s:%d' % (rel, lineno))
            print('      %s' % snippet)
        print('\n공간↔장치 연결의 정본은 geo_binding 입니다. 읽기는')
        print('  aot.space.device_binding'
              ' (device_for_shape / devices_for_shapes / current)')
        print('쓰기는 bind / rebind / unbind / end_all_for_device 를 쓰세요.')
        print('배경: docs/design/geo-device-binding.md (GB-6)\n')

    if ghosts:
        print('FAIL: [GB-6] 명부에 있지만 더 이상 레거시 컬럼을 쓰지 않는 '
              '파일 — LEGACY_COLUMN_USERS 에서 빼세요:\n')
        for rel in ghosts:
            print('  ', rel)
        print()

    if not violations:
        return 1

    print('FAIL: geo 패키지 밖에서 지도 데이터를 직접 씁니다 — %d건\n'
          % len(violations))
    for rel, lineno, label, snippet in violations:
        print('  %s:%d  [%s]' % (rel, lineno, label))
        print('      %s' % snippet)
    print('\n지도 데이터는 geo 패키지가 소유합니다. 다음 문을 사용하세요:')
    print('  장치 배치/해제  aot.aot_flask.geo.device_placement'
          ' (place_device / unplace_device)')
    print('  소속 조회       aot.space.device_membership')
    print('  도형 저장       aot.aot_flask.geo.geo_overlays.GeoOverlayManager')
    print('배경: docs/design/geo-data-integrity.md')
    return 1


if __name__ == '__main__':
    sys.exit(main())
