#!/usr/bin/env python3
"""장치 종류 어휘·마커 종류 리터럴 검사기.

장치 종류→모델 매핑과 지도 마커 종류 `'aot_device'` 는 정본이 하나다.
인라인으로 다시 쓰면 한쪽만 늘어나 조용히 갈린다(L1c 이전에 10곳이 이랬다).

규칙:
  1. 문자열 키 'input'·'output' 이 있고 값이 모델 클래스 이름(Input, Output,
     CustomController, Function, PID, Trigger, Conditional, Camera)인 dict
     리터럴을 거부한다. `aot.space.device_kind.models_for` 를 쓴다.
  2. 문자열 상수 'aot_device' 를 거부한다(독스트링 제외).
     `aot.databases.geo_marker_kinds.MARKER_TYPE` 을 쓴다.
  SQL(트리거 DDL, alembic) 안의 리터럴은 대상이 아니다.

사용: python3 aot/scripts/check_device_kind_literals.py
종료 코드 0 = 위반 없음, 1 = 위반 발견.

@phase active
@stability stable
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SCAN_ROOT = os.path.join(ROOT, 'aot')

#: 정본 정의 자리·SQL·테스트 — 저장소 루트 기준 접두사.
EXEMPT_PREFIXES = (
    'aot/space/device_kind.py',
    'aot/space/device_binding.py',   # device_kind_models() 정본
    'aot/databases/geo_marker_kinds.py',
    'aot/databases/geo_integrity_ddl.py',    # SQL 문자열
    'aot/tests/',
    'aot/scripts/check_device_kind_literals.py',
    # 앱 코드를 import 하지 않고 sqlite 를 직접 여는 독립 L0 검사기 — 상수를 못 가져온다.
    'aot/scripts/check_device_location_drift.py',
)

#: 아직 옮기지 못한 것의 명부(허가 목록이 아니다 — 비워야 끝난다).
#: L1b 가 상수 import 로 바꾸면 지운다.
LEGACY_MARKER_USERS = ()

MODEL_NAMES = {'Input', 'Output', 'CustomController', 'Function', 'PID',
               'Trigger', 'Conditional', 'Camera'}


def _docstring_nodes(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, 'body', [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def check_source(src, rel):
    """(줄, 메시지) 위반 목록."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    docs = _docstring_nodes(tree)
    marker_ok = rel in LEGACY_MARKER_USERS
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and node.value == 'aot_device'
                and id(node) not in docs and not marker_ok):
            out.append((node.lineno,
                        "'aot_device' 리터럴 — geo_marker_kinds.MARKER_TYPE 을 쓰세요"))
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            vals = [v.id for v in node.values if isinstance(v, ast.Name)]
            if {'input', 'output'} <= keys and any(v in MODEL_NAMES for v in vals):
                out.append((node.lineno,
                            "장치 종류→모델 dict 리터럴 — "
                            "device_kind.models_for 를 쓰세요"))
    return out


def main():
    bad = 0
    for base, dirs, files in os.walk(SCAN_ROOT):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', 'node_modules')]
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(base, f)
            rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
            if any(rel.startswith(p) for p in EXEMPT_PREFIXES):
                continue
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
            for line, msg in check_source(src, rel):
                print('%s:%d: %s' % (rel, line, msg))
                bad += 1
    if bad:
        print('\n위반 %d건' % bad)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
