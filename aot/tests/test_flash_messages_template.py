# coding=utf-8
"""flash_messages.html — 서버 flash 가 토스트로 전달되는지 검사한다.

`window.__aotFlashNotice` 가 토스트가 있을 때 자기 자신을 다시 불러 스택이
넘쳤던 결함(RangeError)의 재발 방지 테스트.
"""
import json
import os
import re
import shutil
import subprocess
import unittest

import jinja2

_TEMPLATES = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'aot_flask', 'templates')


def _render(flashed):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(_TEMPLATES))
    env.globals['_'] = lambda s: s
    env.globals['get_flashed_messages'] = (
        lambda category_filter=(): [m for c, m in flashed
                                    if c in category_filter])
    env.policies['json.dumps_function'] = json.dumps
    return env.get_template('flash_messages.html').render()


class FlashMessagesTemplateTest(unittest.TestCase):

    def test_notice_function_does_not_call_itself(self):
        html = _render([])
        body = html.split('window.__aotFlashNotice = function', 1)[1]
        body = body.split('})();', 1)[0]
        self.assertNotIn('__aotFlashNotice(', body)
        self.assertIn('window.showToast(message, kind)', body)

    @unittest.skipUnless(shutil.which('node'), 'node 없음')
    def test_flash_reaches_show_toast(self):
        html = _render([('success', 'saved'), ('error', 'failed')])
        scripts = '\n'.join(re.findall(r'<script>(.*?)</script>', html, re.S))
        driver = (
            "var calls = [];"
            "var window = {showToast: function (m, k) { calls.push([m, k]); }};"
            "var toastr = {};"
            "var document = {};"
            + scripts +
            ";console.log(JSON.stringify(calls));")
        out = subprocess.run(['node', '-e', driver], capture_output=True,
                             text=True, check=True).stdout
        self.assertEqual(json.loads(out), [['Success: saved', 'success'],
                                           ['Error: failed', 'error']])


if __name__ == '__main__':
    unittest.main()
