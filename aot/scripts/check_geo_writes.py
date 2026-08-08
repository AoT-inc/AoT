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
  - 그 밖의 모듈은 geo 패키지의 공개 함수를 쓴다:
      장치 배치      aot.aot_flask.geo.device_placement.place_device
      배치 해제      aot.aot_flask.geo.device_placement.unplace_device
      소속 조회      aot.aot_flask.geo.device_membership
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
    'aot/aot_flask/api/geo.py',        # geo REST 리소스
    'aot/aot_flask/routes_geo.py',     # geo 페이지·API 라우트
    'aot/aot_flask/cli_geo.py',        # geo 스키마 마이그레이션 CLI
    'aot/aot_flask/utils/utils_map_config.py',   # 지도 설정 수명주기
    'aot/databases/',                  # 모델 정의·DDL
    'aot/scripts/',                    # 진단·점검 스크립트
    'aot/tests/',                      # 테스트
)

# 장치 삭제 시 자기 마커를 정리하는 경로 — 소유자는 아니지만 정당하다.
# 게이트웨이(unplace_device)로 옮기는 것이 목표이며, 그때까지 명시 예외로
# 둔다. 새 항목을 추가하지 말 것.
GRANDFATHERED = {
    'aot/aot_flask/utils/utils_input.py',
    'aot/aot_flask/utils/utils_output.py',
    'aot/services/tab_service.py',
}

# 쓰기로 간주하는 호출. 읽기(query/filter_by/all/first)는 대상이 아니다 —
# 읽기는 오염을 만들지 않고, 막으면 정당한 조회까지 마비된다.
#
# [GB-7] GeoBinding 포함: 공간↔장치 연결의 정본이므로 GeoShape 와 같은
# 소유권 규칙을 받는다. 장치 삭제 경로 17곳이 각자 바인딩을 종료시키기
# 시작하면 "슬롯당 현재 1개"·"종료는 valid_to 기록" 같은 규칙을 열일곱 벌
# 구현하게 되고, 그 중 하나만 빠뜨려도 조용히 고아가 생긴다 — 도형이
# 정확히 그렇게 썩었다. 밖에서는 geo 패키지의 게이트웨이를 쓴다.
WRITE_CLASSES = ('GeoShape', 'GeoFacility', 'GeoBinding')

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
        for p in sorted(GRANDFATHERED):
            print('  ', p)
        return 0

    violations = scan()
    if not violations:
        print('OK: geo 패키지 밖의 지도 데이터 쓰기 없음.')
        return 0

    print('FAIL: geo 패키지 밖에서 지도 데이터를 직접 씁니다 — %d건\n'
          % len(violations))
    for rel, lineno, label, snippet in violations:
        print('  %s:%d  [%s]' % (rel, lineno, label))
        print('      %s' % snippet)
    print('\n지도 데이터는 geo 패키지가 소유합니다. 다음 문을 사용하세요:')
    print('  장치 배치/해제  aot.aot_flask.geo.device_placement'
          ' (place_device / unplace_device)')
    print('  소속 조회       aot.aot_flask.geo.device_membership')
    print('  도형 저장       aot.aot_flask.geo.geo_overlays.GeoOverlayManager')
    print('배경: docs/design/geo-data-integrity.md')
    return 1


if __name__ == '__main__':
    sys.exit(main())
