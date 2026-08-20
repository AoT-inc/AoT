# coding=utf-8
"""[현황] 카드의 **항목 표시/숨김** — 조용히 깨지는 자리만 지킨다.

시설이 커지면 [현재]와 [제어 상태]에 줄이 계속 늘어난다. 무엇이 볼 값인지는
그 자리를 쓰는 사람만 알아서, 카드 제목 옆 [설정]으로 직접 뺀다. 저장은
`rep_key` 와 **같은 자리**(도형 `meta_json`)다.

여기서 잡는 것은 셋이다.

1. **거르는 것은 화면이 한다.** 서버가 감춘 항목을 응답에서 빼 버리면 설정
   창이 목록을 만들 수 없어 **다시 켤 방법이 사라진다.** 에러는 안 난다 —
   그냥 그 줄이 영영 돌아오지 않는다.
2. **경고는 감출 수 없다.** 편차("못 따라감")·안전 게이트는 아래 숫자가 왜
   그런지의 이유라, 목록에 넣으면 카드가 거짓말을 한다(냉각기 100% 만 남고
   그것이 나쁜 신호라는 사실이 사라진다).
3. **전부 켜면 흔적을 남기지 않는다.** 빈 목록을 저장해 두면 기본값과 같은
   뜻인데 읽는 쪽이 매번 판단해야 한다.
"""
import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..')
_POPUP = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                      'AoT_map', 'aot-map-popup.js')
_WIDGET = os.path.join(_ROOT, 'aot_flask', 'static', 'js', 'widgets',
                       'AoT_map', 'aot-map-widget-vector.js')
_KO = os.path.join(_ROOT, 'aot_flask', 'translations', 'ko',
                   'LC_MESSAGES', 'messages.po')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class TestHiddenRowsReader(unittest.TestCase):
    """`hidden_rows_of` 는 무엇을 믿고 무엇을 버리는가."""

    def _fake(self, meta):
        return type('S', (), {'meta_json': meta})()

    def test_reads_both_cards(self):
        from aot.aot_flask.geo.site_summary import hidden_rows_of
        got = hidden_rows_of(self._fake(
            {'hidden_rows': {'now': ['RH'], 'control': ['curtain']}}))
        self.assertEqual({'now': ['RH'], 'control': ['curtain']}, got)

    def test_missing_is_empty_not_error(self):
        """설정한 적 없는 도형이 정상이다 — 대부분이 그렇다."""
        from aot.aot_flask.geo.site_summary import hidden_rows_of
        self.assertEqual({}, hidden_rows_of(self._fake(None)))
        self.assertEqual({}, hidden_rows_of(self._fake({})))
        self.assertEqual({}, hidden_rows_of(self._fake({'rep_key': 'T'})))

    def test_junk_is_dropped_not_raised(self):
        """손으로 고친 meta_json 이 모달을 통째로 죽이면 안 된다."""
        from aot.aot_flask.geo.site_summary import hidden_rows_of
        self.assertEqual({}, hidden_rows_of(self._fake({'hidden_rows': 'RH'})))
        self.assertEqual({}, hidden_rows_of(self._fake(
            {'hidden_rows': {'now': 'RH'}}))) 
        self.assertEqual({'now': ['RH']}, hidden_rows_of(self._fake(
            {'hidden_rows': {'now': ['RH', '', None, 3]}})))

    def test_unknown_card_is_ignored(self):
        """카드 이름은 어휘다 — 오타가 조용히 저장되면 아무 데도 안 쓰인다."""
        from aot.aot_flask.geo.site_summary import hidden_rows_of
        self.assertEqual({}, hidden_rows_of(self._fake(
            {'hidden_rows': {'nowe': ['RH']}})))


class TestServerStillSendsHiddenRows(unittest.TestCase):
    """**서버는 감춘 항목도 계속 보낸다.** 응답에서 빼면 다시 켤 수 없다."""

    def test_reader_is_only_used_to_fill_the_response(self):
        """읽기 함수를 부르는 자리가 늘면 **거르는 데 쓰기 시작한 것**이다.

        서버가 감춘 항목을 응답에서 빼면 설정 창이 목록을 만들 수 없어 다시
        켤 방법이 사라진다 — 에러는 안 나고, 그 줄이 영영 돌아오지 않는다.
        늘려야 할 정당한 이유가 생기면 그때 이 숫자를 올리되, **거르는 용도가
        아닌지** 먼저 확인할 것.
        """
        expected = {'aot_flask/routes_geo.py': 2,     # 응답 1 + 저장 후 반환 1
                    'aot_flask/routes_geo_iec.py': 1}  # 응답 1
        for path, n in expected.items():
            src = _read(os.path.join(_ROOT, path))
            got = len(re.findall(r'\bhidden_rows_of\(', src))
            self.assertEqual(n, got,
                             '%s 의 hidden_rows_of 호출이 %d → %d 로 바뀌었다. '
                             '응답을 거르는 데 쓰고 있지 않은지 확인할 것.'
                             % (path, n, got))

    def test_both_responses_carry_the_setting(self):
        """구역·시설 응답 **둘 다** 실어야 한다 — 한쪽만 실으면 그쪽 카드만
        설정이 먹고, 증상은 '저장은 되는데 화면이 안 바뀐다' 다."""
        self.assertIn("'hidden_rows': hidden_rows_of(zone)",
                      _read(os.path.join(_ROOT, 'aot_flask/routes_geo.py')))
        self.assertIn("'hidden_rows': hidden_rows",
                      _read(os.path.join(_ROOT, 'aot_flask/routes_geo_iec.py')))

    def test_empty_selection_removes_the_key(self):
        """전부 켠 상태를 빈 목록으로 남기지 않는다."""
        src = _read(os.path.join(_ROOT, 'aot_flask/routes_geo.py'))
        body = src.split('def _save_hidden_rows', 1)[1].split('\n@', 1)[0]
        self.assertIn('rows.pop(card, None)', body)
        self.assertIn("meta.pop('hidden_rows', None)", body)

    def test_save_is_one_implementation(self):
        """시설이 자기 저장 로직을 따로 들지 않는다 — 갈리면 검사 규칙이
        조용히 어긋난다(rep_key 가 실제로 그랬다)."""
        src = _read(os.path.join(_ROOT, 'aot_flask/routes_geo_iec.py'))
        self.assertIn('from aot.aot_flask.routes_geo import _save_hidden_rows',
                      src)

    def test_meta_is_copied_before_write(self):
        """제자리 수정은 SQLAlchemy 가 못 본다 — 에러 없이 저장만 안 된다.
        `output_order` 처럼 이미 값이 있는 도형에서만 조용히 실패한다."""
        src = _read(os.path.join(_ROOT, 'aot_flask/routes_geo.py'))
        body = src.split('def _save_hidden_rows', 1)[1].split('\n@', 1)[0]
        self.assertIn('meta = dict(shape.meta_json or {})', body)
        self.assertIn("rows = dict(meta.get('hidden_rows') or {})", body)


class TestWarningsAreNotHideable(unittest.TestCase):
    """편차·안전 게이트는 목록에 없어야 한다."""

    def test_control_choices_only_offer_vent_and_kinds(self):
        src = _read(_POPUP)
        body = src.split('function controlRowChoices', 1)[1].split('\n  }', 1)[0]
        for banned in ('strain', 'gate'):
            self.assertNotIn(banned, body,
                             '경고(%s)가 감출 수 있는 항목으로 들어갔다 — '
                             '감추면 카드가 거짓말을 한다.' % banned)
        self.assertIn('outputs_by_kind', body)
        self.assertIn("'vent'", body)

    def test_control_filter_does_not_touch_the_warning_rows(self):
        """실제로 거르는 자리도 경고를 건드리지 않는다."""
        src = _read(_POPUP)
        # 게이트·편차를 그리는 줄에 ctrlHidden 이 끼면 안 된다.
        block = src.split("var strain = summary.strain;", 1)[1] \
                   .split("var V = window.AoTViz;", 1)[0]
        self.assertNotIn('ctrlHidden', block)


class TestWiringFootguns(unittest.TestCase):

    def test_each_card_binds_only_its_own_button(self):
        """카드마다 목록의 출처가 다르고 거는 쪽이 둘이다. 한쪽이 pane 안의
        버튼을 전부 걸면 남의 카드에 **빈 목록을 아는 핸들러**가 붙는다 —
        실제로 겪었다(제어 카드의 [설정]이 아무 일도 하지 않았다)."""
        src = _read(_POPUP)
        body = src.split('function wireCardConfig', 1)[1].split('\n  }', 1)[0]
        self.assertNotIn("querySelectorAll('[data-card-cfg]')", body,
                         'pane 안의 [설정] 버튼을 전부 걸고 있다.')
        self.assertIn("[data-card-cfg=\"' + card + '\"]", body)

    def test_binding_is_idempotent(self):
        """[현황]은 30초마다 다시 그려지는데 내용이 같으면 DOM 을 그대로 둔다
        (깜빡임 방지) — 표시가 없으면 리스너만 쌓인다."""
        src = _read(_POPUP)
        body = src.split('function wireCardConfig', 1)[1].split('\n  }', 1)[0]
        self.assertIn('cfgBound', body)

    def test_card_name_comes_from_the_caller(self):
        """어느 카드인지를 `source` 가 비었는지로 짐작하면, 코디네이터가 없는
        시설(summary 없음)에서 제어 카드가 [현재]로 잘못 걸린다."""
        src = _read(_WIDGET)
        self.assertIn("'now', readings)", src)
        self.assertIn("'control', (res[0] || {}).summary)", src)


class TestStringsAreTranslated(unittest.TestCase):
    """새 문구가 한국어 화면에 영어로 남지 않게."""

    def test_new_msgids_have_korean(self):
        po = _read(_KO)
        for msgid in ('Choose which items to show',
                      'All items in this card are hidden.',
                      'Nothing to show here yet.'):
            m = re.search(r'^msgid "%s"\nmsgstr "(.*)"$' % re.escape(msgid),
                          po, re.M)
            self.assertIsNotNone(m, '번역 항목이 없다: %s' % msgid)
            self.assertTrue(m.group(1).strip(), '번역이 비었다: %s' % msgid)


if __name__ == '__main__':
    unittest.main()
