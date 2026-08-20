# -*- coding: utf-8 -*-
"""버튼의 **역할과 강조**가 어긋나지 않게 지킨다.

`aot-pill-btn-primary`(브랜드 딥그린)는 "권하는 동작" 이라는 뜻이다. 그런데
삭제 버튼 42곳이 저장·복제와 똑같은 딥그린이었다 — 장치 설정 모달의 푸터는
[닫기][삭제][복제][저장]이 전부 같은 색이라, 되돌릴 수 없는 것과 아무 일도
없는 것이 화면상 구분되지 않았다.

색을 새로 만들지 않았다. `aot-pill-btn-danger` 는 이미 앱에 있었고(백업 삭제,
방법 삭제, 스케줄러, 캘린더 위젯) **일부 화면만 그것을 쓰고 있었다** — 규칙이
없던 것이 아니라 지켜지지 않던 것이다.

이 검사가 없으면 다음에 삭제 버튼을 만드는 사람은 옆에 있는 저장 버튼을
복사한다. 그렇게 42건이 됐다.
"""
import os
import re
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOTS = [
    os.path.join(_ROOT, 'aot_flask', 'templates'),
    os.path.join(_ROOT, 'aot_flask', 'static', 'js'),
    os.path.join(_ROOT, 'widgets'),
]
_SKIP_DIR = (os.sep + 'dist', 'node_modules')   # 번들은 재빌드 산출물
# layout.html 은 기동 시 layout_default.html 로 덮어써진다(정본이 아니다).
# widget_template_*.html 은 widgets/*.py 에서 생성된다.
_SKIP_FILE = ('layout.html',)
_SKIP_SUB = ('widget_template_',)

_DELETE = re.compile(r'delete|삭제|Delete|data-del\b', re.I)
_DISMISS = re.compile(
    r"_\(\s*'(Close|Cancel)'\s*\)|>\s*(닫기|취소)\s*<|value=_\('(Close|Cancel)'\)")
# 클래스를 토글하는 코드(탭 강조 등)는 버튼의 역할과 무관하다.
_NOT_A_BUTTON = re.compile(r'classList|removeClass|addClass|Deleted')


def _files():
    for root in _ROOTS:
        for dirpath, _dirnames, filenames in os.walk(root):
            if any(s in dirpath for s in _SKIP_DIR):
                continue
            for name in sorted(filenames):
                if not name.endswith(('.html', '.js', '.py')):
                    continue
                if name in _SKIP_FILE or any(s in name for s in _SKIP_SUB):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8') as fh:
                    yield path, fh.read()


# **줄 단위로 보면 놓친다.** 여는 태그의 class 와 라벨이 다른 줄에 있는 버튼이
# 실제로 있었고(geo_input_entry.html 의 삭제), 줄 단위 검사는 그것을 통과시켰다.
# 그래서 여는 태그부터 라벨 뒤 한 조각까지를 **하나의 버튼**으로 본다.
_BUTTON = re.compile(
    r'<(?:button|a|input)\b[^>]*?aot-pill-btn[^>]*?>[^<]{0,120}|'
    r'\{\{\s*[\w.]+\(\s*class_=[\'"][^\'"]*aot-pill-btn[^\'"]*[\'"][^}]{0,200}',
    re.S)


def _buttons():
    """(경로, 줄번호, 버튼 조각) — 여러 줄에 걸친 버튼도 한 덩어리로 낸다."""
    for path, text in _files():
        for m in _BUTTON.finditer(text):
            yield path, text[:m.start()].count('\n') + 1, m.group(0)


def _footer_blocks(text):
    """modal-footer 의 범위. **div 깊이를 센다** — 첫 `</div>` 로 자르면 푸터
    안에 `<span>`/`<div>` 래핑이 있는 화면에서 블록이 반토막 난다."""
    for m in re.finditer(r'<div[^>]*class="[^"]*modal-footer[^"]*"[^>]*>', text):
        i, depth = m.end(), 1
        while depth and i < len(text):
            nxt, close = text.find('<div', i), text.find('</div', i)
            if close == -1:
                break
            if nxt != -1 and nxt < close:
                depth += 1
                i = nxt + 4
            else:
                depth -= 1
                i = close + 5
        yield m.end(), i


class TestDeleteIsNeverPrimary(unittest.TestCase):

    def test_no_delete_button_is_styled_as_the_recommended_action(self):
        bad = []
        for path, lineno, line in _buttons():
            if 'aot-pill-btn-primary' not in line:
                continue
            if not _DELETE.search(line) or _NOT_A_BUTTON.search(line):
                continue
            bad.append('%s:%d' % (os.path.relpath(path, _ROOT), lineno))
        self.assertEqual(
            bad, [],
            '삭제 버튼이 기본 동작(primary)으로 강조돼 있다 — '
            'aot-pill-btn-danger 를 쓸 것:\n  ' + '\n  '.join(bad))

    def test_no_close_or_cancel_button_is_the_recommended_action(self):
        """[닫기]·[취소]는 권하는 동작이 아니다.

        35곳이 [저장]과 똑같은 딥그린이었다. 삭제와 달리 위험하지는 않지만,
        푸터의 모든 버튼이 같은 색이면 강조가 아무것도 뜻하지 않게 된다 —
        "오른쪽 끝이 기본 동작" 이라는 규칙이 화면에서 사라진다.

        `data-dismiss="modal"` 이 붙은 버튼도 같이 본다. 창을 닫는 것이 그
        버튼의 전부라는 뜻이라, 라벨이 무엇이든 권하는 동작일 수 없다.
        """
        bad = []
        for path, lineno, line in _buttons():
            if 'aot-pill-btn-primary' not in line:
                continue
            if _NOT_A_BUTTON.search(line):
                continue
            if not (_DISMISS.search(line) or 'data-dismiss' in line):
                continue
            bad.append('%s:%d' % (os.path.relpath(path, _ROOT), lineno))
        self.assertEqual(
            bad, [],
            '닫기·취소가 기본 동작(primary)으로 강조돼 있다:\n  ' +
            '\n  '.join(bad))

    def test_the_danger_style_actually_exists(self):
        """색을 새로 만들지 않았다는 전제 자체를 고정한다. 정의가 사라지면
        위 검사는 통과하는데 화면의 삭제 버튼은 아무 색도 없어진다."""
        css = os.path.join(_ROOT, 'aot_flask', 'static', 'css',
                           'aot-modal-modern.css')
        with open(css, encoding='utf-8') as fh:
            body = fh.read()
        self.assertIn('.btn.aot-pill-btn.aot-pill-btn-danger {', body)
        block = body.split('.btn.aot-pill-btn.aot-pill-btn-danger {', 1)[1]
        self.assertIn('--aot-color-danger', block.split('}', 1)[0])


class TestOnlyTheLastFooterButtonIsPrimary(unittest.TestCase):
    """푸터에서 **강조는 마지막 하나뿐**이다.

    18개 푸터가 [복제]와 [저장]을 똑같이 강조하고 있었다. 둘 다 딥그린이면
    강조가 "권하는 동작" 이 아니라 그냥 배경색이 된다.

    규칙을 자리로 정한 이유: 무엇이 기본 동작인지는 화면마다 다르지만, 오른쪽
    끝이 기본 동작이라는 **자리 약속**은 어느 화면에서나 같다. 그래서 세 곳은
    색이 아니라 순서를 고쳤다 — 저장이 첫 번째였던 대시보드 메뉴, 저장 뒤에
    [AI 컨텍스트]가 있던 GIS 입력.
    """

    def test_no_footer_has_two_recommended_actions(self):
        bad = []
        for path, text in _files():
            if not path.endswith('.html'):
                continue
            for start, end in _footer_blocks(text):
                seg = text[start:end]
                if seg.count('aot-pill-btn-primary') > 1:
                    bad.append('%s:%d' % (os.path.relpath(path, _ROOT),
                                          text[:start].count('\n') + 1))
        self.assertEqual(
            bad, [],
            '한 푸터에 강조된 버튼이 둘 이상이다 — 마지막 하나만 남길 것:\n  '
            + '\n  '.join(bad))



if __name__ == '__main__':
    unittest.main()
