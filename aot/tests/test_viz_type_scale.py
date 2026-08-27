# coding=utf-8
"""`aot-viz` 는 **자기 글자 크기를 주장하지 않는다** (2026-08-27).

사용자 지적: *"옵션에 추가한 aot-viz 스타일 중 텍스트 크기에 관해서 function
모달창의 텍스트 크기와 달라서 이질감이 있습니다."*

실측한 원인 — 두 파일이 다른 사다리를 쓰고 있었다:

    aot-viz (토큰)          모달 (하드코딩 rem, 토큰 0회 / 리터럴 26회)
      .aot-viz  base 0.95     .aot-modal-option-label   0.85   ← 옆줄
      눈금·축   xs   0.75     .aot-modal-option-control 0.85
                              .aot-modal-body-text      0.80   ← 사다리 밖

`.aot-viz` 가 0.95 를 못박고 있어서 옆줄(0.85)보다 한 단계 컸다.

## 고른 방향

**글자 크기는 담는 화면이 정한다.** 프리미티브가 그것을 주장하면 어디에 놓든
한 곳은 어긋나고, 그 한 곳마다 예외 규칙이 하나씩 는다. 그래서 `.aot-viz` 는
`inherit` 이고, **어디에 놓였는지 아는 쪽**(어댑터·그릇)이 크기를 정한다.

실측 결과:

    설정 모달   밴드·눈금 라벨 13.6px = 옆줄 라벨 13.6px      (전 15.2)
    프로그램    드로어 13.92px 를 그대로 따름                  (전 15.2)
    지도 팝업   `.aot-ov-block` 이 base 를 명시 → 그대로 15.2
"""
import os
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _css(*parts):
    with open(os.path.join(_ROOT, 'aot_flask', 'static', 'css', *parts),
              encoding='utf-8') as fh:
        return fh.read()


def _rule(css, selector):
    """`selector { … }` 본문 → str. 없으면 None."""
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    return m.group(1) if m else None


class TestThePrimitiveDoesNotAssertASize(unittest.TestCase):

    def test_the_root_inherits(self):
        body = _rule(_css('components', 'aot-dataviz.css'), '.aot-viz')
        self.assertIsNotNone(body, '.aot-viz 규칙이 없다')
        m = re.search(r'font-size:\s*([^;]+);', body)
        self.assertIsNotNone(m, 'font-size 선언이 사라졌다')
        self.assertEqual(m.group(1).strip(), 'inherit',
                         '프리미티브가 다시 자기 크기를 주장한다')

    def test_inner_labels_keep_their_relative_size(self):
        """눈금·축 라벨은 본문과의 **관계**(보조 정보)이지 절대 크기가 아니다 —
        그것까지 상속시키면 보조와 본문이 같아진다."""
        css = _css('components', 'aot-dataviz.css')
        self.assertIn('--aot-font-size-xs', css)


class TestTheAdapterSetsTheSize(unittest.TestCase):
    """`.aot-viz` 가 크기를 안 정하면 누가 정하는가 — 모달 안에 있다는 것을
    아는 쪽이다.

    ⚠ 이 둘은 `.aot-modal-option-control` **밖**에 있다(행의 직계 자식). 그래서
      그 규칙(0.85rem)을 못 받는다 — 상속에만 맡기면 모달 본문 크기를 받아
      오히려 더 커진다(실측으로 확인).
    """

    def test_the_input_wrappers_declare_it(self):
        css = _css('components', 'aot-dataviz.css')
        body = _rule(css, '.aot-scale-input,\n.aot-range-band')
        self.assertIsNotNone(body, '어댑터 규칙을 못 찾았다')
        self.assertIn('--aot-font-size-sm', body,
                      '어댑터가 크기를 안 정한다 — viz 가 그릇보다 커진다')

    def test_it_matches_the_neighbouring_label(self):
        """견줄 대상은 **옆줄 라벨**이다 — 사용자가 이질감을 느낀 자리가
        거기다(밴드가 그 옆에 나란히 선다).

        ⚠ 모달은 토큰을 안 쓰고 리터럴 rem 을 쓴다(26곳). 그래서 값으로
          비교한다 — 한쪽만 바뀌면 여기서 갈린다.
        """
        tokens = _css('aot-theme-variables.css')
        m = re.search(r'--aot-font-size-sm:\s*([\d.]+)rem', tokens)
        self.assertIsNotNone(m)
        sm = float(m.group(1))
        label = _rule(_css('aot-modal-modern.css'), '.aot-modal-option-label')
        self.assertIsNotNone(label, '모달 옵션 라벨 규칙이 없다')
        got = re.search(r'font-size:\s*([\d.]+)rem', label)
        self.assertIsNotNone(got, '모달 옵션 라벨에 크기가 없다')
        self.assertAlmostEqual(float(got.group(1)), sm, places=3,
                               msg='어댑터 토큰(sm)과 모달 라벨이 갈렸다 — '
                                   'viz 가 다시 옆줄과 달라진다')


class TestContainersThatNeedTheirOwnSizeStillHaveIt(unittest.TestCase):
    """⚠ `inherit` 로 바꾸면 **자기 크기가 없는 그릇**은 페이지 크기를 받는다.

    지도 팝업이 그 경우인데, `.aot-ov-block` 이 "본문 기준 크기" 를 이미
    명시하고 있어 영향이 없다. 그 선언이 사라지면 팝업의 값 표시가 조용히
    커지므로 여기서 함께 잡는다.
    """

    def test_the_map_popup_block_declares_base(self):
        body = _rule(_css('widget', 'aot-sensor-label.css'), '.aot-ov-block')
        self.assertIsNotNone(body, '.aot-ov-block 규칙이 없다')
        self.assertIn('--aot-font-size-base', body,
                      '지도 팝업 그릇이 크기를 잃었다 — viz 가 페이지 크기를 받는다')


if __name__ == '__main__':
    unittest.main()
