"""기본 MCP 표면 = 도메인(2026-11 전환). AOT_MCP_SURFACE=legacy 로 옛 표면에 되돌린다."""
import os
import unittest
from unittest import mock

from aot.tools.tool_execution import domain_surface_enabled


class SurfaceDefaultTest(unittest.TestCase):

    def _with(self, value):
        env = {k: v for k, v in os.environ.items() if k != 'AOT_MCP_SURFACE'}
        if value is not None:
            env['AOT_MCP_SURFACE'] = value
        return mock.patch.dict(os.environ, env, clear=True)

    def test_unset_means_domain(self):
        with self._with(None):
            self.assertTrue(domain_surface_enabled())

    def test_blank_and_domain_mean_domain(self):
        for v in ('', ' ', 'domain', 'DOMAIN'):
            with self._with(v):
                self.assertTrue(domain_surface_enabled(), v)

    def test_legacy_spellings_turn_it_off(self):
        for v in ('legacy', 'Legacy', 'classic', '0', 'false', 'no', 'off'):
            with self._with(v):
                self.assertFalse(domain_surface_enabled(), v)
