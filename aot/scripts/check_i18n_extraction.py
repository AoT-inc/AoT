#!/usr/bin/env python3
"""i18n extraction blind-spot checker.

pybabel's Python extractor only recognizes `_()`/`gettext()`/`ngettext()`/
`lazy_gettext()`/`lg()` calls whose argument is a literal string. Two shapes
are invisible to it, so a translatable string written that way never makes
it into messages.pot/.po -- it stays untranslated forever, no matter how
many times `pybabel extract`/`update` runs:

  1. The call sits *inside* an f-string expression, e.g.
     f'<div>{_("Legend")}</div>'. Fix: pull the call out into a variable
     before the f-string and interpolate the variable instead.
     (This exact pattern caused every AoT_map overlay legend title added
     after the initial gis_* input files to silently stay in English.)

  2. The call's argument is not a literal, e.g. `_(info['name'])`. Fix:
     wrap each literal at its point of definition -- with `lg`
     (lazy_gettext) if it lives in a module-level dict, since eager `_()`
     there evaluates once at import time under whatever locale happened to
     be active then -- and use the already-translated value directly at
     the call site instead of calling `_()`/`lg()` on it again.

Parses each file with `ast` (not regex) so multi-line calls, embedded JS
inside string literals, and unrelated uses of a bare `_` as a throwaway
variable are not mistaken for the problem. Exit code 0 = clean; 1 = blind
spots found.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AOT_DIR = os.path.join(ROOT, "aot")

IGNORE_DIR_PARTS = (
    "functions/custom_functions",
    "actions/custom_actions",
    "inputs/custom_inputs",
    "outputs/custom_outputs",
    "widgets/custom_widgets",
    "tests",
    "user_python_code",
    "aot_flask/static",
    "aot_flask/translations",
    "__pycache__",
    # Dev tooling with intentional dynamic re-translation of already
    # extracted strings; not runtime UI code.
    "scripts/generate_doc_translations.py",
)

GETTEXT_FUNCS = {"_", "gettext", "ngettext", "lazy_gettext", "lg"}


def should_skip(path):
    rel = os.path.relpath(path, AOT_DIR).replace(os.sep, "/")
    return any(part in rel for part in IGNORE_DIR_PARTS)


def iter_py_files():
    for dp, dns, fns in os.walk(AOT_DIR):
        dns[:] = [d for d in dns if not should_skip(os.path.join(dp, d) + "/")]
        for fn in fns:
            if fn.endswith(".py"):
                full = os.path.join(dp, fn)
                if not should_skip(full):
                    yield full


def is_gettext_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in GETTEXT_FUNCS
        and node.args
    )


def find_calls(tree):
    """Yield every gettext-family Call node anywhere in the tree."""
    for node in ast.walk(tree):
        if is_gettext_call(node):
            yield node


def is_str_literal(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def check_file(path, text):
    findings = []
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as e:
        return [(e.lineno or 0, "syntax error while parsing", str(e))]

    # 1) f-string-embedded calls: any JoinedStr whose FormattedValue
    #    subtrees contain a gettext-family Call.
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    for call in ast.walk(value.value):
                        if is_gettext_call(call):
                            arg_repr = ast.dump(call.args[0])[:60]
                            findings.append(
                                (node.lineno, "f-string-embedded gettext call", arg_repr)
                            )

    # 2) dynamic (non-literal) first argument, anywhere (including inside
    #    f-strings, already caught above by rule 1, so this additionally
    #    catches plain dynamic calls like _(info['name'])).
    for call in find_calls(tree):
        first = call.args[0]
        if not is_str_literal(first):
            snippet = ast.dump(first)[:70]
            findings.append((call.lineno, "dynamic (non-literal) argument", snippet))

    return findings


def main():
    total = 0
    for path in sorted(iter_py_files()):
        text = open(path, encoding="utf-8").read()
        findings = check_file(path, text)
        if findings:
            rel = os.path.relpath(path, ROOT)
            for lineno, kind, snippet in findings:
                print(f"{rel}:{lineno}: {kind}: {snippet}")
                total += 1

    if total:
        print(f"\n{total} i18n extraction blind spot(s) found. "
              f"These strings will never be translated regardless of pybabel update.")
        return 1
    print("OK: no f-string-embedded or dynamic-argument gettext calls found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
