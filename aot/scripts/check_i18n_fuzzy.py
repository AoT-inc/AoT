#!/usr/bin/env python3
"""Fuzzy-translation checker for aot_flask/translations/*/LC_MESSAGES/messages.po.

`pybabel compile` silently drops any msgid marked `#, fuzzy` from the
compiled .mo -- the app falls back to showing the untranslated (English)
source string. `pybabel update` marks an entry fuzzy whenever it can't find
an exact msgid match and instead borrows the msgstr from a textually
similar entry, *including cases where the "similar" entry is unrelated*
(false positive). This has repeatedly meant previously-correct, working
Korean translations silently reverting to English after an unrelated
`pybabel extract`/`update` run -- with no warning, because the .po file
still *looks* translated (msgstr is non-empty) and only the fuzzy flag
gives it away.

Run this after every `aot/scripts/generate_translations_pybabel.sh` and
before compiling/deploying. By default checks `ko` only (the actively
maintained locale); pass --all to check every locale.

Exit code 0 = no fuzzy entries; 1 = fuzzy entries found (review required:
either the borrowed msgstr is correct and the fuzzy flag can be dropped,
or it needs a real translation).
"""
import argparse
import glob
import os
import sys

import polib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRANSLATIONS_DIR = os.path.join(ROOT, "aot", "aot_flask", "translations")


def check_po(path):
    po = polib.pofile(path)
    return [e for e in po if "fuzzy" in e.flags]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="check every locale, not just ko")
    parser.add_argument("--locale", action="append", help="check a specific locale (repeatable)")
    args = parser.parse_args()

    if args.locale:
        locales = args.locale
    elif args.all:
        locales = sorted(os.path.basename(os.path.dirname(os.path.dirname(p))) for p in
                          glob.glob(os.path.join(TRANSLATIONS_DIR, "*", "LC_MESSAGES", "messages.po")))
    else:
        locales = ["ko"]

    total = 0
    for locale in locales:
        po_path = os.path.join(TRANSLATIONS_DIR, locale, "LC_MESSAGES", "messages.po")
        if not os.path.exists(po_path):
            continue
        fuzzy = check_po(po_path)
        if fuzzy:
            rel = os.path.relpath(po_path, ROOT)
            print(f"{rel}: {len(fuzzy)} fuzzy entr{'y' if len(fuzzy) == 1 else 'ies'}")
            for e in fuzzy[:20]:
                print(f"  msgid {e.msgid[:60]!r} -> msgstr {e.msgstr[:60]!r}")
            if len(fuzzy) > 20:
                print(f"  ... and {len(fuzzy) - 20} more")
            total += len(fuzzy)

    if total:
        print(f"\n{total} fuzzy entr{'y' if total == 1 else 'ies'} found across {len(locales)} "
              f"locale(s). These will be silently excluded by `pybabel compile` -- the app will "
              f"show the English source string instead. For each: either the borrowed "
              f"translation is correct (remove the fuzzy flag) or it needs fixing.")
        return 1
    print(f"OK: no fuzzy entries in {', '.join(locales)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
