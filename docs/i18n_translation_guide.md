# i18n / Translation Guide (for Claude & developers)

This project's **base (source) language is English**. Every user-facing string must
be written in English in the source and wrapped with a translation function so that
Flask-Babel can extract it and serve localized text (Korean, etc.) at runtime.

This guide documents the exact workflow used when internationalizing newly added
files. Follow it whenever you add or touch UI-facing strings.

---

## 1. Where strings live and how to wrap them

| Context | Import | Wrap with | Notes |
|---------|--------|-----------|-------|
| Flask routes / request-time code | `from flask_babel import gettext as _` | `_('English text')` | Evaluated per-request, respects the user's locale. |
| Module-level constants, form choices, `*_INFORMATION` dicts (actions/widgets/inputs) | `from flask_babel import lazy_gettext` | `lazy_gettext('English text')` | Use **lazy** at import time — the locale isn't known yet. |
| Jinja2 templates | (built-in) | `{{ _('English text') }}` | `_` is available in templates by default. |
| Inline JS inside Jinja templates | (built-in) | `{{ _('English text') }}` rendered server-side | Server renders the string before the JS runs. |
| External `.js` files (`static/js/**`) | global `window._` | `window._('English text')` | See the JS bridge below. Use the safe form `(window._ ? window._('English') : 'English')` where `window._` may be undefined early. |

### JS translation bridge (`static/js/**`)

External JS cannot use Jinja. Translation works through a runtime bridge:

1. `babel.cfg` has `[javascript: **.js]` with keyword `_`, so `pybabel extract` picks up
   `_('…')` / `window._('…')` literals from `.js` files into the catalog.
2. `routes_locale_api.get_js_translations` serves the **entire compiled `ko`/locale
   catalog** as `window.AOT_I18N = {msgid: msgstr, …}` (a `<script>` tag in
   `layout_default.html`).
3. `window._ = (key) => window.AOT_I18N[key] || key;` — the helper looks the English
   msgid up in the catalog and falls back to the English string. So a `.js` string is
   translated by the **same `.po`/`.mo`** as Python/Jinja — no separate JS catalog.

Practical rules for `.js`:
- Wrap user-facing strings: `el.textContent = window._('Loading…')`.
- Comments (`//`, `/* */`), `console.*` debug strings, and **string literals used to
  match data values** (e.g. `if (kind === '측창')` matching Korean values returned by an
  external API) are **NOT** UI — leave them (translate comments to English, keep data
  literals as-is).
- For interpolation, wrap the static part and keep the JS template literal:
  `` `${n} ${window._('selected')}` ``.

### Placeholders (interpolation)

Use **named** placeholders, never positional `{}` inside a translatable string, so
translators can reorder them:

```python
flash(gettext('Error querying notes: %(err)s', err=err), 'error')
gettext('Period: %(label)s', label=period_label)
gettext('%(num)d notes', num=len(notes))
```

`flask_babel.gettext(string, **vars)` performs `string % vars` for you.

### What NOT to wrap

- **Comments and docstrings** — translate them to plain English, but do **not** wrap.
- **Log messages** (`self.logger.*`, `logging`) — make them English, but do **not**
  wrap (logs are for operators, not localized UI).
- **Daemon-context strings with no Flask request** and **anything under
  `custom_functions/`, `custom_actions/`, `custom_inputs/`, `custom_outputs/`,
  `custom_widgets/`** — these paths are **ignored** by `babel.cfg`, so wrapping them
  does nothing. Just write plain English.
- **Stored default values** that are persisted to the DB (e.g. a default record name)
  — use a plain English string.

---

## 2. babel configuration

`aot/babel.cfg` controls extraction. Key points:

- Extracts from `**.py`, `**.js`, and Jinja templates under
  `aot_flask/templates/**.html` and `aot_flask/user_templates/**.html`.
- **Ignores**: all `custom_*/**` module folders, `tests/**`, `aot_flask/static/lib`,
  `dist`, `apps`, `manual`, `uploads`, and `aot_flask/translations/**`.

Keyword functions recognized during extraction: `_`, `gettext`, `ngettext`,
`lazy_gettext`, and the alias `lg` (`from flask_babel import lazy_gettext as lg`,
used by `config/__init__.py` and ~39 other files — omitting `-k lg` silently drops
their msgids and `pybabel update` will obsolete the existing translations).

> **GOTCHA — JS template literals.** Babel's JS extractor does NOT extract
> `_('…')` calls inside template-literal interpolations (`` `${_('key')}` ``).
> Those msgids only enter the catalog via the transpiled bundles in
> `aot_flask/static/js/dist/**` — so `js/dist` must stay extractable (do not add
> it to the ignore list). `node_modules` and `vendor` under `static/js` are ignored.

---

## 3. Regenerating translation files

The catalogs live in `aot/aot_flask/translations/`:
- `messages.pot` — extraction template (all source msgids).
- `<lang>/LC_MESSAGES/messages.po` — per-language catalog (msgid → msgstr).
- `<lang>/LC_MESSAGES/messages.mo` — compiled binary loaded at runtime.

`pybabel` must be on PATH. On this dev machine it is provided by **miniforge**
(`/Users/gwansuk/miniforge3/bin/pybabel`), **not** the project `env/` venv. On the
deploy server use `env/bin/pybabel` (see `aot/scripts/upgrade_commands.sh`).

### Step A — Extract (regenerate `messages.pot`)

```bash
cd aot
pybabel extract \
  --project "AoT" --version "<version>" \
  --copyright "Kyle T. Gabriel" \
  --msgid-bugs-address "aot@kylegabriel.com" \
  -s -F babel.cfg -k _ -k gettext -k ngettext -k lazy_gettext -k lg \
  -o aot_flask/translations/messages.pot .
```

Then merge the Integrated Environment Control strings (it lives under
`functions/custom_functions/env_coordinator_impl/`, which `babel.cfg` ignores) —
see the IEC extract+merge block in `aot/scripts/generate_translations_pybabel.sh`.
Skipping this obsoletes ~117 existing IEC msgids.

(Or run the project script: `aot/scripts/generate_translations_pybabel.sh`, which does
extract (incl. `-k lg` + IEC merge) + update using `env/bin/pybabel`.)

Widget templates note: strings embedded in `aot/widgets/*.py` template blocks are
extracted from the **generated** `aot_flask/templates/user_templates/widget_template_*.html`
files, not from the `.py` sources. After wrapping strings in a widget `.py`, regenerate
first: `docker exec aot_local-aot-app-1 python -c "from aot.utils.widget_generate_html import generate_widget_html; generate_widget_html()"`.

### Step B — Update every `.po` from the template

```bash
cd aot
pybabel update --ignore-obsolete --update-header-comment \
  -i aot_flask/translations/messages.pot -d aot_flask/translations
```

This propagates new/changed msgids to all language catalogs. Expect large diffs:
`#:` source-location comments shift whenever line numbers move — this churn is normal
and matches the official script's output.

> **WARNING — fuzzy auto-matches.** `pybabel update` may guess a translation for a new
> msgid by copying a similar existing one and marking it `#, fuzzy`. These guesses are
> frequently **wrong**, and a placeholder mismatch (e.g. a `%(err)s` msgstr attached to
> a `%(label)s` msgid) will make `pybabel compile` fail with
> `unknown named placeholder`. After an update, **clear bad fuzzy entries** for your new
> strings (set `msgstr` empty + drop the `fuzzy` flag so they fall back to English), and
> for `ko` fill in the correct Korean. See the helper pattern in Step C.

### Step C — Fill in `ko` translations (and fix fuzzies)

Because the source language is now English, the **Korean** users only keep seeing Korean
if `ko/LC_MESSAGES/messages.po` maps each new English `msgid` to the original Korean
`msgstr`. Use `polib`:

```python
import polib, glob
KO = {  # English msgid -> Korean msgstr (the original wording you replaced)
    'Notes Report': '노트 보고서',
    'Error querying notes for the report: %(err)s': '보고서 노트 조회 중 오류: %(err)s',
    # ...
}
NEW = set(KO)
for path in glob.glob('aot/aot_flask/translations/*/LC_MESSAGES/messages.po'):
    lang = path.split('/')[-3]
    po = polib.pofile(path)
    for e in po:
        if e.msgid not in NEW:
            continue
        if lang == 'ko':
            e.msgstr = KO[e.msgid]
            e.flags = [f for f in e.flags if f != 'fuzzy']
        elif 'fuzzy' in e.flags:        # wipe wrong guesses in other langs
            e.msgstr = ''
            e.flags.remove('fuzzy')
    po.save(path)
```

> **GOTCHA — Babel's false `python-format` detection.** `pybabel compile` auto-detects
> a message as `python-format` from its **content**, even with no `#, python-format`
> flag, and then requires the translation's `%` tokens to match the source's. Babel's
> regex treats `%` + optional-space + a conversion letter `[diouxXeEfFgGcrs%]` as a
> placeholder — so plain English like `"22% drives"` (`% d`), `"0% command"` (`% c`),
> `"100% retracts"` (`% r`) is **misread as a format spec**, and a Korean translation
> without that exact `% <letter>` sequence fails to compile with
> `placeholders are incompatible`. Removing the flag via polib does **not** help (Babel
> re-detects from content). Fix at the **source**: reword so no `%` is immediately
> followed by (optional space then) a conversion letter — e.g. `"22% drives the motor"`
> → `"22% maps to motor position"`, `"100% retracts it"` → `"100% pulls it back"`. A `%`
> followed by `)`, `.`, a digit, or a non-`[diouxXeEfFgGcrs%]` letter is safe.

> **GOTCHA — real placeholders must survive translation.** A translation that drops a
> `%(name)s` the source has (or adds one it doesn't) also fails compile. Validate before
> saving: compare `re.findall(r'%\([a-zA-Z_]+\)[sd]', msgid)` against the same on the
> translation, and skip/fix any mismatch. The batch-apply script below does this.

### Step C.5 — Cross-check for Babel's silent extraction gaps (do not skip)

Babel's extractors (both the JS lexer and the Jinja2 extractor) have been observed to
**silently drop individual `_()`/`window._()` calls** in large files — not the whole
file, just scattered calls within it. Confirmed cases: `window._('Thermal')` in
`aot-map-widget-vector.js` (a 360KB+ source file) was never extracted by any
`pybabel extract` pass, which meant a `pybabel update` silently deleted its existing
Korean translation. `{{_('1w')}}`, `{{_('1m')}}`, `{{_('Display Graph')}}` etc. in
`graph-async.html` had the same problem via the Jinja2 extractor. Root cause not fully
diagnosed (suspected tokenizer/call-stack desync that self-corrects later in the file);
treat it as a known Babel limitation, not something `-k` flags fix.

**"100% of POT-extracted msgids are translated" does NOT mean "100% of source `_()`
calls are covered."** After every extract+update+fill pass, run an independent
regex-based cross-check:

```python
import re, glob
from babel.messages.pofile import read_po

STR = r"(['\"])((?:\\.|(?!\1).)*)\1"
patterns = {
    'py':   re.compile(r"\b(?:_|gettext|lazy_gettext|lg)\(\s*" + STR),
    'html': re.compile(r"\{\{\s*_\(\s*" + STR),
    'js':   re.compile(r"window\._\(\s*" + STR),
}
# scan **/*.py, aot_flask/templates/**/*.html, aot_flask/static/js/**/*.js
# (exclude node_modules/, vendor/, custom_*/, user_templates/)
# collect all literal first-argument strings, decode \' \" \\ escapes.

with open('aot_flask/translations/ko/LC_MESSAGES/messages.po', 'rb') as f:
    cat_ids = {m.id for m in read_po(f, locale='ko') if m.id and not isinstance(m.id, tuple)}

missing = [s for s in all_found if s not in cat_ids]
# filter false positives:
#  (a) concatenation fragments — a string that is a PREFIX of some existing msgid is
#      just the first segment of an implicit multi-line Python string concat that
#      Babel's tokenizer (correctly) joined; skip it.
#  (b) dist-bundle unicode-escape artifacts — esbuild/rollup sometimes writes real
#      unicode chars in the dist bundle as literal `\uXXXX` text; decode with
#      `codecs.decode(s, 'unicode_escape')` and skip if the decoded form is already
#      in the catalog.
```

For genuinely missing msgids found this way, do **not** just re-run `pybabel extract`
— it will hit the same silent-drop bug again. Instead, patch `messages.pot` and
`ko/LC_MESSAGES/messages.po` directly with `babel.messages.pofile.read_po`/`write_po`
(`cat.add(msgid, string=translation, locations=[...])`), then `pybabel compile`.

**Known msgid collision, not fixed:** `"1m"` means "1 month" in `graph-async.html`
(rangeSelector `type: 'month'`) but "1 minute" in `AoT_graph.py` (rangeSelector
`type: 'minute'`) — the same English string, two different meanings, and gettext has
no per-call disambiguation without `pgettext`/`msgctxt` (which this codebase doesn't
use). Currently translated as "1개월" (month), which is wrong on the minute-range
button in `AoT_graph.py`. Fixing properly requires either adopting `pgettext` or
changing one of the source labels to a distinct string — out of scope for a
translation-only pass; flag it if touching either file.

### Step D — Compile `.mo`

```bash
cd aot
pybabel compile -d aot_flask/translations
```

Must finish with **0 errors**. Verify a sample:

```python
import gettext
t = gettext.translation('messages', 'aot/aot_flask/translations', languages=['ko'])
print(t.gettext('Notes Report'))   # -> 노트 보고서
```

On the deploy server the equivalent command is
`aot/scripts/upgrade_commands.sh compile-translations`
(or `docker-compile-translations` in Docker).

---

## 4. Quick audit commands

Find hardcoded Korean (CJK Hangul) in target files:

```bash
python3 -c "import re; \
[print(i+1,l) for i,l in enumerate(open('PATH',encoding='utf-8').read().splitlines()) \
 if re.search(r'[가-힣]', l)]"
```

Confirm a Python file still parses after edits:

```bash
python3 -c "import ast; ast.parse(open('PATH').read())"
```

---

## 5. Checklist when internationalizing a new/changed file

1. Identify UI strings vs. comments/logs vs. babel-ignored daemon code.
2. UI strings → English + `gettext` / `lazy_gettext` (named placeholders).
3. Comments, docstrings, log messages, `custom_*` code → plain English (no wrap).
4. Extract → update → fix fuzzies + fill `ko` → compile (Steps A–D).
5. `pybabel compile` must report 0 errors; spot-check `ko.mo`.
6. Commit the source files **and** the `messages.pot` / `*.po` / `*.mo` changes
   together.
