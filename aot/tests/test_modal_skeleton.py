# coding=utf-8
"""모달 골격 — **CSS 가 없는 클래스를 마크업에 달지 않는다** (2026-08-27).

## 어떻게 알게 됐나

구획 페이지가 편집 모달을 드로어로 바꾸면서 `aot-modal-header` 가 사라졌다.
그것을 보고 "현대화 골격이 부트스트랩으로 후퇴했다" 고 읽었는데 **틀렸다** —
`aot-modal-header` 는 어떤 CSS 에도 정의가 없는 **유령 클래스**였다.

현대화는 클래스 이름이 아니라 **컨테이너와 CSS** 가 한다:

    <div class="modal fade aot-option-modal …">     ← 이것이 골격이다
      <div class="modal-header">                     ← CSS 가 이 이름을 겨냥한다

    aot-modal-modern.css:
      .aot-option-modal .modal-header       { min-height:36px; … }
      .aot-option-modal .modal-header .modal-title  { font-size:18px; … }
      .aot-option-modal .modal-header .close::before { … }

드로어 21개 전부가 이 형태다. 이름을 바꾸면 위 규칙이 선택자를 잃어 **고치려던
것과 정반대로** 헤더가 부트스트랩 기본으로 돌아간다.

## 유령 클래스가 왜 해로운가

아무 일도 하지 않으면서 읽는 사람에게 "이것이 골격" 이라는 잘못된 신호를 준다.
실제로 그 신호 때문에 27블록을 고칠 뻔했다. 스타일이 붙지 않으므로 지워도
화면은 그대로다.
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_FLASK = os.path.join(_HERE, '..', 'aot_flask')

# 이름은 `aot-modal-*` 인데 CSS 정의가 없던 것들. 되살리면 같은 오해가 반복된다.
_GHOSTS = ('aot-modal-header', 'aot-modal-footer', 'aot-modal-close')


def _walk(*roots):
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in ('node_modules', 'dist', '__pycache__')]
            for fn in filenames:
                if fn.endswith(('.html', '.js', '.py')):
                    yield os.path.join(dirpath, fn)


def _css_defines(name):
    """어떤 CSS 파일이든 이 클래스를 선택자로 쓰는가."""
    pat = re.compile(r'\.%s\b' % re.escape(name))
    for dirpath, dirnames, filenames in os.walk(os.path.join(_FLASK, 'static', 'css')):
        for fn in filenames:
            if not fn.endswith('.css'):
                continue
            with open(os.path.join(dirpath, fn), encoding='utf-8') as fh:
                if pat.search(fh.read()):
                    return True
    return False


def test_the_ghost_classes_have_no_css():
    """전제가 무너지면(누군가 CSS 를 붙이면) 아래 검사의 뜻이 바뀐다.

    그때는 유령이 아니므로 `_GHOSTS` 에서 빼고, 어느 골격을 쓸지 다시 정할 것.
    """
    for name in _GHOSTS:
        assert not _css_defines(name), (
            "'%s' 에 CSS 가 생겼다 — 더 이상 유령이 아니다. 이 명부에서 빼고 "
            "골격 규칙을 다시 정할 것" % name)


def test_no_template_carries_a_ghost_class():
    offenders = []
    for path in _walk(os.path.join(_FLASK, 'templates'),
                      os.path.join(_FLASK, 'static', 'js'),
                      os.path.join(_HERE, '..', 'widgets')):
        try:
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        # ⚠ **주석 블록을 통째로 지우고 본다.** 한 줄씩 `{#` 로 판정하면
        #   여러 줄짜리 Jinja 주석의 가운데 줄이 걸린다 — 규칙을 설명하는
        #   주석이 규칙 위반이 되는 셈이다(CLAUDE.md 가 AST 검사에서 같은
        #   함정을 적어 두었다).
        stripped = re.sub(r'\{#.*?#\}', '', src, flags=re.S)
        stripped = re.sub(r'<!--.*?-->', '', stripped, flags=re.S)
        stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.S)
        stripped = '\n'.join(
            '' if ln.lstrip().startswith(('#', '//')) else ln
            for ln in stripped.splitlines())
        for name in _GHOSTS:
            if re.search(r'\b%s\b' % re.escape(name), stripped):
                offenders.append(os.path.relpath(path, _HERE))
                break
    assert not offenders, (
        'CSS 가 없는 유령 클래스를 달고 있다 — 아무 일도 안 하면서 "이것이 '
        '골격" 이라는 잘못된 신호를 준다: %s' % offenders)


def test_the_real_skeleton_is_the_container():
    """`.aot-option-modal` 이 골격이라는 사실을 CSS 로 확인한다.

    이 규칙들이 사라지면 드로어 21개의 헤더가 한꺼번에 부트스트랩 기본으로
    돌아간다 — 그때는 화면 전체가 바뀌므로 눈에 띄지만, 근거는 여기 남긴다.
    """
    path = os.path.join(_FLASK, 'static', 'css', 'aot-modal-modern.css')
    with open(path, encoding='utf-8') as fh:
        css = fh.read()
    for sel in ('.aot-option-modal .modal-header',
                '.aot-option-modal .modal-header .modal-title',
                '.aot-option-modal .modal-header .close'):
        assert sel in css, '현대화 규칙이 사라졌다: %s' % sel
