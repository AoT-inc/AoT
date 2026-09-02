# coding=utf-8
"""함수 상태 문장이 **뷰어의 언어로** 나가는지 지킨다.

데몬에는 요청 컨텍스트가 없어 `gettext` 가 로케일로 풀리지 않는다. 그래서
컨트롤러는 사실(`status_facts`)만 내보내고 문장은 Flask 쪽
(`aot_flask/utils/utils_function_status.py`)이 만든다.

이 계열의 실패는 전부 **조용하다** — 번역이 없으면 영어가 그대로 나가고,
컨트롤러에 문장이 되살아나면 어느 쪽이 화면에 나가는지 상황마다 달라진다.
둘 다 에러가 아니라서 테스트 말고는 알 방법이 없다.
"""
import os
import re
import unittest

from aot.tests.test_map_popup_labels import _js_map, _po_entries

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..')
_RENDERER = os.path.join(_ROOT, 'aot_flask', 'utils', 'utils_function_status.py')
_TRANSLATIONS = os.path.abspath(os.path.join(_ROOT, 'aot_flask', 'translations'))
_CONTROLLERS = {
    'env_coordinator': os.path.join(
        _ROOT, 'functions', 'custom_functions', 'env_coordinator.py'),
    'sequence': os.path.join(_ROOT, 'controllers', 'controller_trigger_sequence.py'),
    'conditional': os.path.join(_ROOT, 'controllers', 'controller_conditional.py'),
}


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _renderer_msgids():
    """렌더러 소스의 `_('...')` 리터럴 전수."""
    return sorted(set(re.findall(r"_\('((?:[^'\\]|\\.)*)'\)", _read(_RENDERER))))


def _app_for(locale):
    """번역만 붙인 최소 Flask 앱.

    AoT 앱 전체를 띄우지 않는다 — 여기서 보는 것은 카탈로그와 렌더러이지
    DB·데몬·확장이 아니고, 그것들을 끌어오면 무관한 이유로 이 검사가 죽는다.
    """
    from flask import Flask
    from flask_babel import Babel
    app = Flask(__name__)
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = _TRANSLATIONS
    app.config['BABEL_DEFAULT_LOCALE'] = locale
    Babel(app, locale_selector=lambda: locale)
    return app


class TestSentencesAreBuiltInFlaskNotTheDaemon(unittest.TestCase):
    """컨트롤러가 문장을 만들면 그것은 영원히 영어다."""

    def test_controllers_emit_facts(self):
        for name, path in _CONTROLLERS.items():
            self.assertIn(
                "'status_facts'", _read(path),
                f"{name} 이 `status_facts` 를 안 내보낸다 — 그러면 위젯에 아무것도 "
                f"안 뜬다(위젯 JS 는 `string_status`/`error` 두 키만 읽는다).")

    def test_no_controller_assembles_status_lines(self):
        """사용자 코드의 `string_status` 를 **전달**하는 것은 정상이다 —
        컨트롤러가 여러 줄을 **조립**하는 것이 금지다. 조립은 join 으로 나타난다."""
        for name, path in _CONTROLLERS.items():
            src = _read(path)
            self.assertNotIn(
                'join(lines)', src,
                f"{name} 이 상태 문장을 조립하고 있다 — 문장은 "
                f"utils_function_status.py 한 곳에서만 만든다.")

    def test_only_the_renderer_holds_the_status_sentences(self):
        """문구가 컨트롤러로 되살아나면 그것은 영원히 영어다."""
        renderer_only = ('Last cycle:', 'Elapsed in cycle:', 'Next check in:',
                         "Today's window:", 'Not checked yet.')
        for name, path in _CONTROLLERS.items():
            src = _read(path)
            for phrase in renderer_only:
                self.assertNotIn(
                    phrase, src,
                    f"{name} 에 상태 문구 {phrase!r} 가 있다 — 데몬에는 요청 "
                    f"컨텍스트가 없어 뷰어의 언어로 바뀌지 않는다.")


class TestLabelVocabularyMatchesTheMapPopup(unittest.TestCase):
    """같은 것을 가리키는 msgid 가 두 벌이 되면 화면마다 다른 말이 나온다."""

    def _renderer_map(self, name):
        body = _read(_RENDERER).split('%s = {' % name, 1)[1].split('}\n', 1)[0]
        return dict(re.findall(r"'([\w_]+)':\s*'([^']*)'", body))

    def test_mode_labels_reuse_the_popup_msgids(self):
        self._assert_subset('_MODE_LABELS', '_MODE_LABELS')

    def test_kind_labels_reuse_the_popup_msgids(self):
        self._assert_subset('_KIND_LABELS', '_KIND_LABELS')

    def test_var_labels_reuse_the_popup_msgids(self):
        self._assert_subset('_VAR_LABELS', '_LIMIT_LABELS')

    def _assert_subset(self, py_name, js_name):
        py, js = self._renderer_map(py_name), _js_map(js_name)
        for code, label in py.items():
            self.assertIn(
                code, js,
                f"{py_name}[{code!r}] 이 지도 팝업 {js_name} 에 없다 — 어휘가 갈렸다.")
            self.assertEqual(
                label, js[code],
                f"{py_name}[{code!r}] 의 msgid 가 지도 팝업과 다르다 — 번역이 "
                f"두 벌이 되어 화면마다 다른 말이 나온다.")


class TestEveryMsgidIsTranslated(unittest.TestCase):
    """번역이 빠지면 그 줄만 영어로 남는다 — 에러는 안 난다."""

    def _translations(self, locale):
        po = _read(os.path.join(_TRANSLATIONS, locale, 'LC_MESSAGES', 'messages.po'))
        return dict(_po_entries(po))

    def test_ko_and_ja_cover_every_renderer_msgid(self):
        msgids = _renderer_msgids()
        self.assertGreater(len(msgids), 20, "렌더러의 msgid 를 못 읽었다")
        for locale in ('ko', 'ja'):
            table = self._translations(locale)
            missing = [m for m in msgids if not table.get(m)]
            self.assertEqual(
                [], missing,
                f"{locale} 번역 누락 {len(missing)}건: {missing}")

    def test_no_msgid_carries_a_literal_percent(self):
        """babel 이 python-format 으로 읽어 `pybabel compile` 이 거부한다.

        거부되면 그 문구 하나가 아니라 **그 언어 전체**가 영어로 나온다.
        퍼센트 기호는 msgid 가 아니라 값 쪽에 붙인다.
        """
        for msgid in _renderer_msgids():
            self.assertNotIn(
                '%', re.sub(r'%\([a-z_]+\)s', '', msgid),
                f"msgid 에 리터럴 %% 가 있다: {msgid!r}")


class TestRendering(unittest.TestCase):
    """사실 → 문장. 판정이 틀려도 에러가 안 나므로 결과를 직접 본다."""

    def _render(self, data, locale='ko'):
        from aot.aot_flask.utils import utils_function_status
        with _app_for(locale).test_request_context('/'):
            return utils_function_status.localize(dict(data)).get('string_status')

    def test_env_coordinator_lines_are_korean(self):
        text = self._render({'status_facts': {
            'kind': 'env_coordinator', 'paused': None, 'age_s': 12.0,
            'summary': {
                'modes': ['cooling', 'degraded'],
                'photo': {'temp': 29.3, 'rh': 67.0, 'vpd': 1.25},
                'deviation': {'temperature': 8.52},
                'outputs_by_kind': {'opening': 40.0},
                'vent': {'open_ratio_pct': 40.0,
                         'effective_area_m2': 72.0, 'total_area_m2': 179.0},
                'gate': {'triggered': False, 'description': ''},
            }}})
        self.assertIn('모드: 냉방, 일부만 제어', text)
        self.assertIn('온도 +8.52', text)
        self.assertIn('개구부 40%', text)
        self.assertIn('12초 전', text)
        # VPD·CO2 는 앞 라벨이 없으면 무슨 값인지 알 수 없다.
        self.assertIn('VPD 1.25 kPa', text)

    def test_paused_coordinator_says_why(self):
        text = self._render({'status_facts': {
            'kind': 'env_coordinator', 'paused': 'outside_time_window',
            'summary': None, 'age_s': None}})
        self.assertIn('운전 시간대 밖', text)

    def test_sequence_counts_the_steps_in_the_response(self):
        """라우트가 정적 스텝을 나중에 합쳐 넣는다 — 컨트롤러가 센 수를 쓰면 어긋난다."""
        text = self._render({
            'status_facts': {'kind': 'sequence', 'state': 'running',
                             'window_start': '05:30', 'window_end': '21:00',
                             'period_s': 10800, 'in_cycle': True, 'elapsed_s': 3600},
            'steps': [{'is_active': True}, {'is_active': False}, {'is_active': False}]})
        self.assertIn('시퀀스: 실행 중', text)
        self.assertIn('05:30 – 21:00', text)
        self.assertIn('1:00:00', text)
        self.assertIn('3개 중 1개', text)

    def test_conditional_reports_its_run_state(self):
        text = self._render({'status_facts': {
            'kind': 'conditional', 'is_activated': True, 'period_s': 30.0,
            'last_run_age_s': 14.0, 'action_fired': False, 'next_check_s': 16.0}})
        self.assertIn('조건부: 활성화됨', text)
        self.assertIn('주기: 30초', text)
        self.assertIn('마지막 판정: 14초 전', text)
        self.assertIn('다음 판정까지: 16초', text)

    def test_unknown_codes_pass_through_instead_of_vanishing(self):
        """새 모드가 화면에서 조용히 사라지는 것보다 코드가 보이는 편이 낫다."""
        text = self._render({'status_facts': {
            'kind': 'env_coordinator', 'paused': None, 'age_s': 1.0,
            'summary': {'modes': ['brand_new_mode'], 'photo': {}, 'gate': {}}}})
        self.assertIn('brand_new_mode', text)

    def test_untouched_when_there_are_no_facts(self):
        """PID·카메라·사용자가 쓴 Conditional 상태 코드는 자기 문장을 들고 온다."""
        from aot.aot_flask.utils import utils_function_status
        with _app_for('ko').test_request_context('/'):
            data = utils_function_status.localize({'string_status': '사용자 코드 문장'})
        self.assertEqual('사용자 코드 문장', data['string_status'])


if __name__ == '__main__':
    unittest.main()
