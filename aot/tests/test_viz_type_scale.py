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

        ⚠ **토큰 이름으로 견준다.** 값으로 견주면 둘 다 같은 칸을 가리켜도
          한쪽이 리터럴로 되돌아간 것을 못 잡는다 — 그때는 사다리가 다시
          갈라지기 시작한 것이고, 그 조짐이 여기서 보여야 한다.
        """
        label = _rule(_css('aot-modal-modern.css'), '.aot-modal-option-label')
        self.assertIsNotNone(label, '모달 옵션 라벨 규칙이 없다')
        got = re.search(r'font-size:\s*var\((--aot-font-size-[\w-]+)\)', label)
        self.assertIsNotNone(got, '모달 옵션 라벨이 토큰을 안 쓴다')
        self.assertEqual(got.group(1), '--aot-font-size-sm',
                         '어댑터(sm)와 모달 라벨이 다른 칸을 가리킨다 — '
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

class TestTheModalUsesTheScale(unittest.TestCase):
    """모달이 **토큰만** 쓴다 (2026-08-27, 사용자 요청 C).

    예전에는 리터럴 rem 26곳에 서로 다른 크기가 **10가지**였다(1.4 · 1.05 ·
    0.95 · 0.85 · 0.82 · 0.8 · 0.75 · 0.72 · 0.7 · 0.66). 사다리는 다섯
    칸인데 절반이 그 밖이었고, 그 어긋남이 "정돈이 안 됐다" 로 보인다.

    ⚠ **px 는 남는다.** iOS 는 16px 미만 입력칸에서 화면을 확대하므로 그
      16px 은 크기가 아니라 **동작**이다. 사다리에 넣으면 그 이유가 사라지고
      다음 사람이 "왜 여기만 px 인가" 를 물을 자리도 없어진다.
    """

    def test_no_literal_rem_remains(self):
        css = _css('aot-modal-modern.css')
        bad = re.findall(r'font-size:\s*([\d.]+rem)', css)
        self.assertEqual(bad, [], '리터럴 rem 이 되살아났다: %s' % bad)

    def test_the_px_ones_are_still_px(self):
        """16px 은 iOS 확대 방지다 — 토큰으로 바꾸면 그 동작이 깨진다."""
        css = _css('aot-modal-modern.css')
        self.assertIn('font-size: 16px !important', css,
                      '입력칸 16px 이 사라졌다 — iOS 가 화면을 확대한다')

    def test_every_token_used_exists(self):
        """없는 토큰을 쓰면 그 규칙은 조용히 **상속**으로 떨어진다."""
        css = _css('aot-modal-modern.css')
        tokens = _css('aot-theme-variables.css')
        used = set(re.findall(r'var\((--aot-font-size-[\w-]+)\)', css))
        self.assertTrue(used, '토큰을 하나도 안 쓴다')
        for name in sorted(used):
            self.assertIn('%s:' % name, tokens, '없는 토큰: %s' % name)

class TestNoDoubleVersionedAssets(unittest.TestCase):
    """`url_for('static', …)` 뒤에 손으로 `?v=` 를 또 붙이지 않는다 (2026-08-27).

    프레임워크가 이미 **내용 해시**를 붙인다(`app._static_cache_bust`,
    `@app.url_defaults` 로 `endpoint == 'static'` 전부를 덮는다). 그 위에 손으로
    붙이면 `...css?v=<해시>?v=20260825a` 가 된다.

    ## 고장은 아니었다 — 그래서 더 오래 남았다

    해시가 여전히 바뀌므로 캐시 무효화는 계속 작동한다. 대가는 다른 것이다:

      · 손으로 붙인 값이 **아무 일도 안 하는데 관리 대상처럼 보인다.** 파일을
        고친 사람이 그 날짜를 올려야 하나 망설이고, 안 올려도 아무 일이 없다.
      · 어느 쪽이 실제 버전인지 URL 만 보고 알 수 없다.

    ⚠ **리터럴 `/static/…?v=` 는 반대다.** 그쪽은 `url_for` 를 지나지 않아
      프레임워크 해시가 안 붙으므로 `?v=` 가 **반드시 있어야** 한다
      (`check_static_cache_busting.py` 가 그것을 요구한다). 이 검사가 그것까지
      지우게 만들면 안 된다.
    """

    def _templates(self):
        base = os.path.join(_ROOT, 'aot_flask', 'templates')
        for dirpath, _d, names in os.walk(base):
            for n in names:
                if n.endswith('.html'):
                    path = os.path.join(dirpath, n)
                    with open(path, encoding='utf-8') as fh:
                        yield os.path.relpath(path, base), fh.read()

    def test_no_manual_version_after_url_for_static(self):
        bad = []
        for name, src in self._templates():
            if re.search(r"url_for\('static'[^)]*\)\s*\}\}\?v=", src):
                bad.append(name)
        self.assertEqual(sorted(bad), [],
                         'url_for 뒤에 손으로 붙인 ?v= 가 있다')

    def test_literal_references_keep_theirs(self):
        """이 검사가 리터럴의 `?v=` 까지 지우게 만들면 안 된다 — 그쪽은
        프레임워크 해시가 안 붙어 1년 캐시가 곧 "1년간 옛 코드" 가 된다."""
        found = 0
        for _name, src in self._templates():
            found += len(re.findall(r'"/static/[^"]*\?v=', src))
        self.assertGreater(found, 0,
                           '리터럴 참조의 버전이 통째로 사라졌다')


if __name__ == '__main__':
    unittest.main()
