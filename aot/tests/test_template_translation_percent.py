# coding=utf-8
"""템플릿 번역 문자열의 '%' — Jinja 의 gettext 는 늘 %-포맷을 한다.

Flask-Babel 이 까는 Jinja i18n 확장은 newstyle 이라 `{{ _('...') }}` 의 결과를
**변수가 없어도** `rv % variables` 로 한 번 포맷한다. 그래서 템플릿에서 부르는
문자열의 번역에 맨 '%' 가 하나라도 있으면(예: "90% 시간") 그 화면이
`ValueError: incomplete format` 로 500 이 된다. 영어 원문에는 '%' 가 없고 번역에만
있으면 영어 화면은 멀쩡해 눈에 띄지 않는다(2026-09-23 AI → 기록 화면, ko·ja).

규칙: 템플릿에서 쓰는 문자열의 글자 '%' 는 원문·번역 모두 '%%' 로 쓴다.

두 겹으로 막는다.
1. 모든 언어 .po 에서 템플릿 위치(.html)가 붙은 항목의 원문·번역을 훑어,
   '%%' 도 아니고 올바른 자리표시(%(name)s, %s, %d …)도 아닌 '%' 를 찾는다.
2. ko·ja 는 컴파일된 .mo 로 실제 Jinja newstyle gettext 를 돌려 렌더가 되는지 본다
   (원문만 쓰는 영어도 함께).
"""
import gettext
import glob
import os
import re

import pytest

babel_pofile = pytest.importorskip('babel.messages.pofile')
jinja2 = pytest.importorskip('jinja2')

TRANSLATIONS = os.path.join(os.path.dirname(__file__), '..', 'aot_flask', 'translations')

#: '%%' 또는 올바른 %-자리표시 하나.
_TOKEN = re.compile(r"%(?:%|(?:\([^)]*\))?[#0\- +]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa])")
_NAMED = re.compile(r"%\((\w+)\)")
_POSITIONAL = re.compile(r"%(?!%|\()[#0\- +]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa]")

#: 이 검사를 만들 때 이미 있던 항목 — 같은 부류의 결함이지만(툴팁 `(in %)`)
#: 23개 언어와 PID 옵션 템플릿을 함께 고쳐야 해 이 변경의 범위 밖이었다.
#: 전부 '%%' 로 고쳐 이제 비어 있다. **새 항목을 여기에 더하지 말 것** — '%%' 로 고친다.
_KNOWN_EXISTING = frozenset()


def _catalog(path):
    with open(path, 'rb') as fh:
        return babel_pofile.read_po(fh)


AOT_DIR = os.path.join(os.path.dirname(__file__), '..')
_file_cache = {}


def _read(rel):
    if rel not in _file_cache:
        try:
            with open(os.path.join(AOT_DIR, rel), encoding='utf-8') as fh:
                _file_cache[rel] = fh.read()
        except OSError:
            _file_cache[rel] = ''
    return _file_cache[rel]


def _template_entries(cat):
    """템플릿에서 실제로 부르는 항목. .po 의 위치 주석은 낡을 수 있어(옮겨 간
    문자열의 옛 .html 위치가 남는다) 그 템플릿 파일에 원문이 정말 있는지 본다."""
    for m in cat:
        if not m.id or not isinstance(m.id, str):
            continue
        probe = m.id[:60]
        if not any(loc[0].endswith('.html') and probe in _read(loc[0])
                   for loc in m.locations):
            continue
        yield m


def _po_files():
    return sorted(glob.glob(os.path.join(TRANSLATIONS, '*', 'LC_MESSAGES', 'messages.po')))


@pytest.mark.parametrize('po_path', _po_files(),
                         ids=lambda p: p.split(os.sep)[-3])
def test_template_strings_have_no_bare_percent(po_path):
    bad = []
    for m in _template_entries(_catalog(po_path)):
        if m.id in _KNOWN_EXISTING:
            continue
        for text in (m.id, m.string or ''):
            if '%' in _TOKEN.sub('', text):
                bad.append((m.id, text))
    assert not bad, (
        "템플릿 문자열에 맨 '%' 가 있다 — Jinja gettext 가 %-포맷하다 500 이 된다. "
        "'%%' 로 쓸 것: " + repr(bad[:5]))


def _render_all(translations):
    env = jinja2.Environment(extensions=['jinja2.ext.i18n'], autoescape=True)
    env.install_gettext_translations(translations, newstyle=True)
    tmpl = env.from_string('{{ _(m, **kw) }}')
    return tmpl


@pytest.mark.parametrize('lang', ['en', 'ko', 'ja'])
def test_template_strings_render_through_jinja_gettext(lang):
    """실제 렌더 경로 — newstyle gettext 가 `rv % variables` 를 한다."""
    po_path = os.path.join(TRANSLATIONS, 'ko' if lang == 'en' else lang,
                           'LC_MESSAGES', 'messages.po')
    if lang == 'en':
        translations = gettext.NullTranslations()
    else:
        mo_path = po_path[:-3] + '.mo'
        with open(mo_path, 'rb') as fh:
            translations = gettext.GNUTranslations(fh)
    tmpl = _render_all(translations)
    failed = []
    checked = 0
    for m in _template_entries(_catalog(po_path)):
        if m.id in _KNOWN_EXISTING or _POSITIONAL.search(m.id):
            # 위치 자리표시(%s·%d)는 템플릿에서 인자 없이 부를 수 없다 —
            # 그런 항목은 JS 쪽 위치가 함께 붙은 것이라 여기선 건너뛴다.
            continue
        kw = {name: 1 for name in _NAMED.findall(m.id)}
        checked += 1
        try:
            tmpl.render(m=m.id, kw=kw)
        except (ValueError, TypeError, KeyError) as exc:
            failed.append((m.id, repr(exc)))
    assert checked > 500
    assert not failed, failed[:5]


def test_call_quality_percentile_labels_render_in_ko_and_ja():
    """2026-09-23 500 의 직접 회귀 — 이 네 줄이 렌더되고 '%' 하나로 나온다."""
    ids = ('90th percentile time', 'Calls per bundle, 90th percentile',
           'Lookup time, 90th percentile', 'Time between calls, 90th percentile')
    for lang in ('ko', 'ja'):
        mo = os.path.join(TRANSLATIONS, lang, 'LC_MESSAGES', 'messages.mo')
        with open(mo, 'rb') as fh:
            tmpl = _render_all(gettext.GNUTranslations(fh))
        for msgid in ids:
            out = tmpl.render(m=msgid, kw={})
            assert '90%' in out and '%%' not in out, (lang, msgid, out)
