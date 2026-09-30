"""릴리스·공개 발행 도구의 회귀 방지.

- release_helper.promote_unreleased: 「미출시」 절을 릴리스 절로 승격하고 새 빈 절을 연다.
  (옛 동작은 뼈대를 끼워 넣어, 태그 뒤 항목이 릴리스 절에 더해지는 함정을 재현했다.)
- check_origin_push_safety.check_tree_contents: 비공개 전용 파일(CLAUDE.md)이 공개 트리에
  있으면 목록과 무관하게 막는다.
"""
import importlib.util
import os
import subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


release_helper = _load('release_helper', 'aot/scripts/release_helper.py')
push_safety = _load('check_origin_push_safety', 'aot/scripts/check_origin_push_safety.py')

SAMPLE = """# AoT — 변경 이력

소개.

---

# 미출시 (Unreleased)

{note}

## 개선
- 새 항목 A

## 수정
- 새 항목 B

---

# v26.09.07 (2026-09-22) — 이전 판

## 새 기능
- 옛 항목
""".format(note=release_helper.UNRELEASED_NOTE)


def test_promote_moves_body_and_opens_fresh_section():
    out, status = release_helper.promote_unreleased(SAMPLE, '26.09.08', '2026-10-01', '제목')
    assert status == 'promoted'
    assert '# v26.09.08 (2026-10-01) — 제목' in out
    # 새 「미출시」 절은 안내문만 있고 항목은 없다
    head, _, rest = out.partition('# v26.09.08')
    assert release_helper.UNRELEASED_HEADING in head
    assert '새 항목' not in head
    # 항목은 새 릴리스 절로 옮겨졌고, 옛 절은 그대로다
    new_section = rest.split('# v26.09.07')[0]
    assert '새 항목 A' in new_section and '새 항목 B' in new_section
    assert release_helper.UNRELEASED_NOTE not in new_section
    assert out.count('# v26.09.07 (') == 1 and '옛 항목' in out


def test_promote_without_title():
    out, status = release_helper.promote_unreleased(SAMPLE, '26.09.08', '2026-10-01')
    assert status == 'promoted'
    assert '# v26.09.08 (2026-10-01)\n' in out


def test_promote_is_idempotent():
    out, _ = release_helper.promote_unreleased(SAMPLE, '26.09.08', '2026-10-01')
    again, status = release_helper.promote_unreleased(out, '26.09.08', '2026-10-01')
    assert status == 'exists' and again == out


def test_promote_refuses_empty_unreleased():
    empty = SAMPLE.replace('## 개선\n- 새 항목 A\n\n## 수정\n- 새 항목 B\n\n', '')
    _, status = release_helper.promote_unreleased(empty, '26.09.08', '2026-10-01')
    assert status == 'empty'


def test_promote_requires_unreleased_section():
    _, status = release_helper.promote_unreleased('# AoT\n\n# v1.0.0 (2026-01-01)\n', '1.0.1', '2026-10-01')
    assert status == 'no_unreleased'


def test_real_changelog_keeps_old_sections():
    with open(os.path.join(REPO, 'CHANGELOG.md'), encoding='utf-8') as fh:
        content = fh.read()
    before = content.count('\n# v')
    out, status = release_helper.promote_unreleased(content, '99.99.99', '2099-01-01')
    assert status in ('promoted', 'empty')
    if status == 'promoted':
        assert out.count('\n# v') == before + 1
        assert out.count(release_helper.UNRELEASED_HEADING) == 1


def _tree_with(tmp_path, files):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')

    def git(*a):
        return subprocess.run(['git', *a], cwd=tmp_path, env=env, check=True,
                              capture_output=True, text=True).stdout.strip()
    git('init', '-q')
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        git('add', '-f', rel)
    git('commit', '-q', '-m', 'x')
    return git('rev-parse', 'HEAD')


def test_tree_check_blocks_private_only_file(tmp_path, monkeypatch):
    sha = _tree_with(tmp_path, {'CLAUDE.md': 'internal', 'README.md': 'public'})
    monkeypatch.chdir(tmp_path)
    ok, reason = push_safety.check_tree_contents(sha)
    assert ok is False and 'CLAUDE.md' in reason


def test_tree_check_passes_clean_tree(tmp_path, monkeypatch):
    sha = _tree_with(tmp_path, {'README.md': 'public'})
    monkeypatch.chdir(tmp_path)
    ok, _ = push_safety.check_tree_contents(sha)
    assert ok is True
