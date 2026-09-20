# coding=utf-8
"""프로바이더 레지스트리(aot/tools/providers.py) 바인딩 — tools-no-ai 가드의
런타임 짝.

`check_import_layers.py` 는 **정적으로** aot/tools 가 aot.ai 를 import하지
않는다는 것만 본다. 그것만으로는 부족하다 — 등록이 실제로 되는지, 안 된
채로 부르면 조용히 망가지는 대신 알아볼 수 있게 실패하는지는 런타임에만
확인할 수 있다. 이 파일이 그 짝이다.

DB·Flask 앱 컨텍스트를 쓰지 않는다 — 바인딩은 순수하게 함수/객체 등록이고,
프로바이더 콜백 자체(DB 를 만지는 실제 동작)를 실행하지는 않는다.
"""
import unittest

import aot.ai  # noqa: F401 — import 시점에 bind_all() 이 돈다 (aot/ai/__init__.py)
from aot.ai.services.tool_providers import bind_all
from aot.tools import providers


class TestProvidersBoundAfterImportingAotAi(unittest.TestCase):
    """`import aot.ai` 한 번으로 PROVIDER_NAMES 전부가 등록된다."""

    def test_all_provider_names_are_bound(self):
        unbound = [name for name in providers.PROVIDER_NAMES
                  if not providers.is_bound(name)]
        self.assertEqual(
            unbound, [],
            "import aot.ai 이후에도 등록 안 된 프로바이더: %s" % unbound)

    def test_get_returns_a_callable_or_object_with_methods(self):
        """이름마다 뭔가 쓸 수 있는 것(함수 또는 메서드를 가진 객체)이 와야
        한다 — None 이 등록되어 있으면 그것도 조용한 실패다."""
        for name in providers.PROVIDER_NAMES:
            value = providers.get(name)
            self.assertIsNotNone(value, "프로바이더 %r 가 None 으로 등록됨" % name)


class TestProviderNotBound(unittest.TestCase):
    """레지스트리가 비어 있으면 조용한 None 대신 예외를 낸다."""

    def setUp(self):
        # 실제 레지스트리를 건드리므로 teardown 에서 반드시 되돌린다.
        self._saved = dict(providers._REGISTRY)

    def tearDown(self):
        providers._REGISTRY.clear()
        providers._REGISTRY.update(self._saved)

    def test_unbound_provider_raises_clear_error(self):
        providers._reset_for_tests()
        self.assertFalse(providers.is_bound('spatial_hierarchy'))
        with self.assertRaises(providers.ProviderNotBound) as ctx:
            providers.get('spatial_hierarchy')
        # 메시지가 "무엇을, 왜, 어떻게 고치는지" 를 담고 있어야 한다 — 이
        # 예외를 처음 보는 사람은 대개 aot.tools 만 단독으로 로드한 스크립트나
        # 테스트를 짠 사람이다.
        self.assertIn('spatial_hierarchy', str(ctx.exception))
        self.assertIn('aot.ai', str(ctx.exception))

    def test_rebind_after_reset_recovers(self):
        """레지스트리를 비웠다가 bind_all() 을 다시 부르면 원상복구된다 —
        재바인딩이 append-only 가 아니라 멱등이어야 안전하다."""
        providers._reset_for_tests()
        bind_all()
        for name in providers.PROVIDER_NAMES:
            self.assertTrue(providers.is_bound(name), name)


class TestBindAllIsIdempotent(unittest.TestCase):
    """bind_all() 을 두 번 불러도 등록된 이름 집합과 그 정체(같은 값인지)가
    같다 — aot.ai 를 여러 경로로 반복 import 해도 결과가 흔들리면 안 된다."""

    def test_calling_bind_all_twice_gives_same_names(self):
        bind_all()
        first = providers.bound_names()
        bind_all()
        second = providers.bound_names()
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(providers.PROVIDER_NAMES))

    def test_calling_bind_all_twice_gives_same_callables(self):
        """재등록이 매번 새 클로저/객체를 만들어도 무방하지만, 적어도
        타입과 동작은 같아야 한다 — 여기서는 재바인딩 전후로 같은 이름이
        여전히 호출 가능한지만 본다(실제 DB 호출은 하지 않는다)."""
        bind_all()
        for name in providers.PROVIDER_NAMES:
            value_before = providers.get(name)
            bind_all()
            value_after = providers.get(name)
            self.assertEqual(type(value_before), type(value_after), name)


if __name__ == '__main__':
    unittest.main()
