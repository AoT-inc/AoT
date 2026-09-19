# coding=utf-8
"""`migrate_sensor_max_age_default` 의 **보고가 사실대로인가** (2026-09-20).

스크립트는 옛 기본값 120 만 0 으로 눕히는데, 보고 줄이 두 가지로 틀렸다.

1. 120 이 아닌 값을 전부 "사람이 고른 값" 이라 불렀다 — **0 도.** 0 은 옵션의
   현재 기본값이자 "안 정했다" 다. 이미 자동인 설치를 누가 손으로 정한 것처럼
   보고했다(로컬 적용 때 실제로 그렇게 찍혔다).
2. 무엇이 바뀌었든 "코디네이터를 재시작해야" 라고 했다 — 꺼진 수집기 하나만
   바뀌었을 때도.
"""
import ast
import pathlib

import pytest

from aot.scripts import migrate_sensor_max_age_default as mig

SRC = pathlib.Path(mig.__file__)


class TestClassify:

    @pytest.mark.parametrize('value', [120, 120.0, '120', '120.0'])
    def test_옛_기본값은_대상(self, value):
        assert mig.classify(value) == mig.TARGET

    @pytest.mark.parametrize('value', [0, 0.0, '0', None, '', -5, 'abc'])
    def test_0_과_빈_값은_사람이_고른_값이_아니라_자동(self, value):
        assert mig.classify(value) == mig.AUTO

    @pytest.mark.parametrize('value', [1200, 1200.0, '600', 119.9, 121])
    def test_그_밖의_숫자는_사람이_고른_값(self, value):
        assert mig.classify(value) == mig.KEPT

    def test_자동_판단은_정본과_같다(self):
        """0 을 미지정으로 읽는 판단을 스크립트가 따로 들지 않는다."""
        assert 'as_seconds' in SRC.read_text(encoding='utf-8')


class TestRestartNote:

    def test_켜진_것만_짚는다(self):
        note = mig.restart_note([('Env Coordinator', True), ('Ext Context', False)])
        assert 'Env Coordinator' in note and 'Ext Context' not in note

    def test_꺼진_것만_바뀌면_재시작할_것이_없다(self):
        note = mig.restart_note([('Ext Context', False)])
        assert '재시작할 것이 없습니다' in note


def test_모듈을_불러도_앱이_뜨지_않는다():
    """분류만 검사하려는데 앱 전체가 기동하면 안 된다 — 앱 import 는 main() 안."""
    tree = ast.parse(SRC.read_text(encoding='utf-8'))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {getattr(n, 'module', None) or '' for n in top}
    assert 'aot.start_flask_ui' not in names
