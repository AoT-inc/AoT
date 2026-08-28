# coding=utf-8
"""저장하면 모달 내용이 사라지던 것 — 서버는 껍데기만 낸다.

`.aot-scale-input` · `.aot-range-band` · `.aot-env-status` · `.aot-coord-plot`
은 **빈 컨테이너로 나가고** 그 안(`.aot-viz` — 눈금·핸들·밴드·현재값)은
클라이언트가 만든다. 각 모듈의 초기화는 `DOMContentLoaded` 에 한 번 붙는 것이
전부라, 저장 뒤 AJAX 로 갈아 끼운 HTML 은 아무도 꾸며 주지 않는다.

실측(2026-08-28, 코디네이터 설정 모달): 페이지 로드 후 `.aot-viz` **14개** —
저장 뒤 AJAX 로 받은 같은 영역은 **0개**. 껍데기 수는 같았다. 즉 사라진 것이
아니라 **한 번도 그려지지 않은** 것이고, 남는 것이 맨 숫자 입력뿐이라 화면이
텅 빈 것처럼 보였다. 새로고침하면 정상인 이유도 같다.

⚠ **가장 조용한 부분은 목록이 갈라지는 것이다.** 처음 고칠 때 모듈 넷만 적어
`.aot-coord-plot`(재배 중·목표 두 줄)을 빠뜨렸고, "고쳤는데 두 줄만 계속
사라진다" 가 됐다. 그래서 여기서 **꾸미는 모듈 전수와 그 목록을 대조**한다.
"""

import os
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_COMMON = os.path.join(_ROOT, 'aot', 'aot_flask', 'static', 'js', 'common')
_ENHANCE = os.path.join(_COMMON, 'aot-modal-enhance.js')
_PAGES = os.path.join(_ROOT, 'aot', 'aot_flask', 'templates', 'pages')

# 옵션 영역을 꾸미지 **않는** 모듈. 여기 이름을 넣는 것은 "저장 뒤 다시 부를
# 필요가 없다" 는 판단이므로, 새로 넣을 때는 그 근거를 함께 적을 것.
_NOT_DECORATORS = {
    'aot-modal-enhance.js':     '이 파일 자신',
    'aot-modal-scroll-lock.js': '모달 열림/닫힘에 붙는 전역 동작 — 옵션 markup 을 만들지 않는다',
    'aot-tz.js':                '시간대 유틸 — DOM 을 꾸미지 않는다',
    'aot-time-utils.js':        '시각 포맷 유틸',
    'aot-user-i18n.js':         '번역 사전 로더',
}


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _code_only(src):
    """주석·문자열 설명이 검사를 흐리지 않도록 줄 주석을 걷어낸다."""
    out = []
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
            continue
        out.append(line.split('//', 1)[0])
    return '\n'.join(out)


class TestEveryDecoratorIsReInitialised(unittest.TestCase):

    def _listed_modules(self):
        code = _code_only(_read(_ENHANCE))
        block = code[code.index('var MODULES'):]
        block = block[:block.index('];')]
        return set(re.findall(r"name:\s*'([A-Za-z]+)'", block))

    def _decorator_files(self):
        """옵션 markup 을 꾸미는 모듈 = 스스로 초기화하고 `.aot-` 를 훑는 것."""
        found = {}
        for name in sorted(os.listdir(_COMMON)):
            if not name.endswith('.js') or name in _NOT_DECORATORS:
                continue
            code = _code_only(_read(os.path.join(_COMMON, name)))
            if 'DOMContentLoaded' not in code:
                continue
            # `(root || document).querySelectorAll(...)` 형태 = "이 범위를 꾸민다".
            # 선택자가 `.aot-` 로 시작하지 않는 것도 있다(`select.aot-bay-select`,
            # `[data-depends-on]`) — 클래스 이름으로만 찾으면 그 둘을 놓치고,
            # 놓치면 목록에서 빠져도 이 검사가 조용해진다.
            if not re.search(r"\(\s*root\s*\|\|\s*document\s*\)\s*\.querySelectorAll",
                             code) and not re.search(
                             r"querySelectorAll\(\s*['\"][^'\"]*\.aot-", code):
                continue
            exported = re.search(r'window\.(AoT[A-Za-z]+)\s*=', code)
            if exported:
                found[name] = exported.group(1)
        return found

    def test_modal_enhance_covers_every_decorator(self):
        listed = self._listed_modules()
        for filename, global_name in self._decorator_files().items():
            self.assertIn(
                global_name, listed,
                f'{filename} 이 옵션 markup 을 꾸미는데 aot-modal-enhance.js 의 '
                f'MODULES 에 없습니다 — 저장하면 그 종류만 조용히 안 그려집니다')

    def test_listed_modules_actually_exist(self):
        """유령 항목 — 사라진 모듈이 목록에만 남으면 다음 사람이 헷갈린다."""
        exported = set()
        for name in os.listdir(_COMMON):
            if name.endswith('.js'):
                for m in re.findall(r'window\.(AoT[A-Za-z]+)\s*=',
                                    _read(os.path.join(_COMMON, name))):
                    exported.add(m)
        for name in self._listed_modules():
            self.assertIn(name, exported, f'{name} 은 어디에도 없습니다')

    def test_the_helper_is_loaded_in_the_layout(self):
        # layout.html 은 기동 시 layout_default.html 로 덮어써진다 — 정본은 default 다.
        layout = _read(os.path.join(_ROOT, 'aot', 'aot_flask', 'templates',
                                    'layout_default.html'))
        self.assertIn('aot-modal-enhance.js', layout)
        self.assertRegex(layout, r'aot-modal-enhance\.js\?v=',
                         '버전 쿼리가 없으면 1년 캐시가 옛 코드를 계속 실행합니다')


class TestOptionRefreshersUseTheHelper(unittest.TestCase):
    """옵션 영역을 AJAX 로 갈아 끼우는 곳은 셋이고, 셋 다 같아야 한다."""

    PAGES = ('function.html', 'input.html', 'output.html')

    def _refresh_body(self, page):
        src = _read(os.path.join(_PAGES, page))
        self.assertIn('function refreshModalOptions', src, f'{page}')
        body = src.split('function refreshModalOptions', 1)[1]
        return body.split('\n  }', 1)[0]

    def test_each_page_re_enhances_after_swapping(self):
        for page in self.PAGES:
            body = _code_only(self._refresh_body(page))
            self.assertIn(
                'AoTModalEnhance.apply', body,
                f'{page} 가 교체 후 다시 꾸미지 않습니다 — 저장하면 모달이 '
                f'텅 빈 것처럼 보입니다')

    def test_no_page_nests_the_fragment_with_html(self):
        """조각의 뿌리가 컨테이너와 같은 id 라, `.html()` 로 넣으면 한 겹씩 깊어진다.

        `getElementById` 는 바깥 것만 돌려주므로 안쪽은 손이 닿지 않게 되고,
        중복 id 는 이후 어떤 선택자든 조용히 엉뚱한 것을 집게 만든다.
        """
        for page in self.PAGES:
            body = _code_only(self._refresh_body(page))
            self.assertNotIn(
                '.html(new_options)', body,
                f'{page} 가 `.html()` 로 조각을 넣습니다 — replaceWith 를 쓸 것')
            self.assertIn('replaceWith(new_options)', body, f'{page}')


if __name__ == '__main__':
    unittest.main()
