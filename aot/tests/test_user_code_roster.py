# coding=utf-8
"""사용자 코드 파일 명부가 **갈라지지 않는지** 지킨다.

`aot/user_python_code/` 에는 설치마다 다른 파일이 자동 생성된다. 그 이름 규약을
아는 자리가 넷이다 — 만드는 곳 · 지우는 곳 · 기동 고아 청소 · `.gitignore`.
넷이 어긋나면 증상이 전부 조용하다:

    만들기 ≠ 지우기      장치를 지워도 그 코드가 디스크에 남는다. 같은 uuid 가
                        재사용되면 옛 코드가 되살아난다.
    만들기 ≠ 청소        고아가 영영 안 걷힌다.
    만들기 ≠ .gitignore  그 설치의 사용자 코드가 소스처럼 커밋되고, 배포가
                        남의 설치 코드를 덮어쓴다.

이 명부는 이미 **두 번** 갈라졌다(2026-08-14 출력, 2026-08-26 위젯·액션).
"""
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..')
_REPO = os.path.join(_ROOT, '..')


def _read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as fh:
        return fh.read()


def _roster():
    """`USER_CODE_FILES` 를 DB·Flask 없이 읽는다 — 소스에서 직접 판다.

    import 하면 `aot.config` 사슬이 딸려 와 이 검사가 설치 상태에 묶인다.
    명부는 리터럴이므로 소스로 충분하다.
    """
    src = _read(_ROOT, 'utils', 'code_verification.py')
    # ⚠ `'}'` 로 자르면 안 된다 — 파일 이름의 `{}` 자리표시자가 먼저 걸려
    #   명부가 통째로 비고, 그러면 아래 검사들이 전부 공회전한다(작성 중 실제로
    #   그랬다). 줄머리의 `}` 로 자른다.
    body = src.split('USER_CODE_FILES = {', 1)[1].split('\n}', 1)[0]
    return dict(
        (m.group(1), (m.group(2), m.group(3)))
        for m in re.finditer(
            r"'(\w+)':\s*\('([^']+)',\s*'(\w+)'\)", body))


def test_the_roster_is_not_empty():
    """파서가 헛돌면 아래 검사들이 전부 공회전한다."""
    r = _roster()
    assert len(r) >= 5, r


def test_every_generated_prefix_is_in_the_roster():
    """코드가 만드는 파일 이름이 **전부** 명부에 있어야 한다.

    빠지면 그 파일은 아무도 안 지우고 청소도 못 알아본다 — 2026-08-26 에
    위젯(`python_code_`)과 액션(`action_input_python_code_`)이 그랬다.
    """
    known = {pattern for pattern, _model in _roster().values()}
    found = {}
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in ('__pycache__', 'node_modules', 'tests')]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            try:
                src = _read(path)
            except (OSError, UnicodeDecodeError):
                continue
            if 'PATH_PYTHON_CODE_USER' not in src:
                continue
            # `'{}/output_{}.py'.format(PATH_PYTHON_CODE_USER, ...)` 와
            # `os.path.join(PATH_PYTHON_CODE_USER, 'x_{}.py')` 두 모양을 본다.
            for m in re.finditer(r"'(?:\{\}/)?([a-z_]*\{\}\.py)'", src):
                found.setdefault(m.group(1), []).append(
                    os.path.relpath(path, _REPO))

    missing = {p: v for p, v in found.items() if p not in known}
    assert not missing, (
        '명부에 없는 사용자 코드 파일 이름 — 아무도 안 지우고 청소도 못 '
        '알아본다: %s' % missing)


def test_gitignore_covers_every_roster_entry():
    """빠지면 그 설치의 사용자 코드가 **소스처럼 커밋된다.**

    배포가 남의 설치 코드를 덮어쓰는 경로다. 2026-08-26 까지 다섯 중 넷이
    뚫려 있었고, 실제로 커밋된 적이 없어 드러나지 않았다.
    """
    ignore = _read(_REPO, '.gitignore')
    for kind, (pattern, _model) in _roster().items():
        glob = 'aot/user_python_code/' + pattern.replace('{}', '*')
        assert glob in ignore, (
            "'%s' 종류가 .gitignore 에 없다 — 그 설치의 코드가 커밋된다: %s"
            % (kind, glob))


def test_every_roster_model_exists():
    """모델 이름은 문자열이라 **오타가 조용하다.**

    고아 청소가 그 종류를 통째로 건너뛰고(=영영 안 걷힘), 로그는 warning 이라
    기본 설치에서 안 보인다.
    """
    models_src = _read(_ROOT, 'databases', 'models', '__init__.py')
    for kind, (_pattern, model) in _roster().items():
        assert re.search(r'\b%s\b' % re.escape(model), models_src), (
            "'%s' 종류의 모델 %r 을 models 패키지에서 찾지 못했다" % (kind, model))


def test_the_sweep_asks_the_right_table_per_kind():
    """종류마다 **그 종류의 표**에 물어야 한다.

    예전에는 모든 모델의 uuid 를 한 집합에 합쳐 놓고 파일 종류와 무관하게
    대조했다. 그 구조에서는 "어느 모델을 봐야 하는가" 가 코드에 없어서
    **모델을 빼먹어도 아무 신호가 없다** — 그 상태로 종류를 추가하면 살아 있는
    파일이 전부 고아가 되어 사용자 코드가 날아간다.
    """
    src = _read(_ROOT, 'utils', 'code_verification.py')
    block = src.split('def purge_orphan_user_code', 1)[1]
    assert 'live_by_kind' in block, '종류별로 대조하지 않는다'
    assert 'live_by_kind[kind]' in block
    assert 'kind not in live_by_kind' in block, (
        '판단할 수 없는 종류를 건너뛰지 않는다 — 근거 없이 지우게 된다')


def test_longer_prefixes_win_when_names_nest():
    """`input_python_code_` 와 `action_input_python_code_` 처럼 한쪽이 다른
    쪽을 품는 이름이 생기면, 짧은 쪽이 먼저 걸려 종류를 잘못 집는다."""
    src = _read(_ROOT, 'utils', 'code_verification.py')
    block = src.split('def purge_orphan_user_code', 1)[1]
    assert '-len(kv[1][0].split(' in block, '긴 접두를 먼저 보지 않는다'


def test_widget_and_action_deletion_clean_up_their_files():
    """삭제 경로가 실제로 정리를 부르는가 — 명부에 넣는 것만으로는 안 지워진다."""
    dash = _read(_ROOT, 'aot_flask', 'utils', 'utils_dashboard.py')
    assert "delete_python_file('widget'" in dash, '위젯 삭제가 코드 파일을 안 지운다'
    act = _read(_ROOT, 'aot_flask', 'utils', 'utils_action.py')
    assert "delete_python_file('action'" in act, '액션 삭제가 코드 파일을 안 지운다'


def test_deletion_happens_before_the_row_is_gone():
    """행을 지운 뒤에 부르면, 실패했을 때 "누구 것이었나" 를 아는 사람이 없다."""
    for path, kind in ((('aot_flask', 'utils', 'utils_dashboard.py'), 'widget'),
                       (('aot_flask', 'utils', 'utils_action.py'), 'action')):
        src = _read(_ROOT, *path)
        i_file = src.index("delete_python_file('%s'" % kind)
        i_row = src.index('delete_entry_with_id', i_file)
        assert i_file < i_row, '%s: 행을 지운 뒤에 파일을 지우고 있다' % kind
