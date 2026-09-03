#!/usr/bin/env python3
"""Apply reviewed translations to fuzzy entries and clear the fuzzy flag.

Input is a JSON file: a list of {"msgid": str, "msgstr": str} objects.
For each, finds the matching entry (by exact msgid; this catalog has no
msgctxt/plural forms) in the target locale's messages.po, rewrites only
its msgstr line and its "#, fuzzy" flag, and leaves every other line in
the file byte-for-byte untouched.

Why not just load+save with polib/babel: both re-serialize the *entire*
file on save (occurrence-comment line-wrap width, PO header field order),
turning a 176-entry fix into a 6000+ line diff that's pure reformatting
noise and hides the real change from review. This does a surgical
line-level edit instead, then re-parses the result with polib to confirm
it's still well-formed and the edits landed correctly.

Usage:
    python3 aot/scripts/fix_fuzzy_entries.py --locale de --json /path/to/de_fixes.json
"""
import argparse
import json
import os
import re
import sys

import polib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRANSLATIONS_DIR = os.path.join(ROOT, "aot", "aot_flask", "translations")

_ESCAPE_MAP = {"\\": "\\\\", "\"": "\\\"", "\n": "\\n", "\t": "\\t", "\r": "\\r"}
_UNESCAPE_RE = re.compile(r'\\(.)')
_UNESCAPE_MAP = {"\\": "\\", "\"": "\"", "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def po_escape(text):
    return "".join(_ESCAPE_MAP.get(c, c) for c in text)


def po_unescape_line(line):
    """line is the raw content between the outer double quotes of a PO string line."""
    def repl(m):
        return _UNESCAPE_MAP.get(m.group(1), m.group(1))
    return _UNESCAPE_RE.sub(repl, line)


def quoted_line_content(line):
    """Given a line like '"foo bar"' (possibly with trailing/leading whitespace), return foo bar (raw, still escaped)."""
    s = line.strip()
    assert s.startswith('"') and s.endswith('"'), f"not a quoted PO string line: {line!r}"
    return s[1:-1]


def parse_entries(lines):
    """Scan lines for msgid/msgstr blocks (no plurals, no msgctxt in this catalog).

    Returns a list of dicts: {msgid, msgid_start, msgstr_start, msgstr_end, flag_line_idx}
    flag_line_idx is the index of a "#, ..." line immediately preceding this entry's
    comment block that contains a flags list, or None.
    """
    entries = []
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].startswith('msgid "'):
            msgid_start = i
            msgid_parts = [quoted_line_content(lines[i][len('msgid'):].strip())]
            j = i + 1
            while j < n and lines[j].lstrip().startswith('"'):
                msgid_parts.append(quoted_line_content(lines[j]))
                j += 1
            msgid_text = "".join(po_unescape_line(p) for p in msgid_parts)

            if j < n and lines[j].startswith('msgstr "'):
                msgstr_start = j
                k = j + 1
                while k < n and lines[k].lstrip().startswith('"'):
                    k += 1
                msgstr_end = k

                # walk backward from msgid_start to find this entry's comment block
                # (contiguous "#"-prefixed lines directly above, stopping at a blank
                # line or a non-comment line -- i.e. the previous entry's msgstr).
                flag_line_idx = None
                b = msgid_start - 1
                while b >= 0 and lines[b].startswith("#"):
                    if lines[b].startswith("#,"):
                        flag_line_idx = b
                    b -= 1

                entries.append({
                    "msgid": msgid_text,
                    "msgid_start": msgid_start,
                    "msgstr_start": msgstr_start,
                    "msgstr_end": msgstr_end,
                    "flag_line_idx": flag_line_idx,
                })
                i = msgstr_end
                continue
        i += 1
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", required=True)
    parser.add_argument("--json", required=True, help="path to JSON list of {msgid, msgstr}")
    args = parser.parse_args()

    po_path = os.path.join(TRANSLATIONS_DIR, args.locale, "LC_MESSAGES", "messages.po")
    if not os.path.exists(po_path):
        print(f"no such locale catalog: {po_path}", file=sys.stderr)
        return 1

    with open(args.json, encoding="utf-8") as f:
        fixes = json.load(f)

    with open(po_path, encoding="utf-8") as f:
        raw = f.read()
    trailing_newline = raw.endswith("\n")
    lines = raw.split("\n")
    if trailing_newline:
        lines = lines[:-1]

    entries = parse_entries(lines)

    by_msgid = {}
    dupes = set()
    for e in entries:
        if e["msgid"] in by_msgid:
            dupes.add(e["msgid"])
        by_msgid.setdefault(e["msgid"], []).append(e)

    errors = []
    edits = []  # (msgstr_start, msgstr_end, new_msgstr_line, flag_line_idx_to_clear_or_delete)
    applied = 0

    for fix in fixes:
        msgid = fix["msgid"]
        msgstr = fix["msgstr"]
        candidates = by_msgid.get(msgid)
        if not candidates:
            errors.append(f"msgid not found in catalog: {msgid!r}")
            continue
        fuzzy_candidates = [
            e for e in candidates
            if e["flag_line_idx"] is not None and "fuzzy" in lines[e["flag_line_idx"]]
        ]
        if not fuzzy_candidates:
            errors.append(f"msgid not flagged fuzzy (already handled?): {msgid!r}")
            continue
        if len(fuzzy_candidates) > 1:
            errors.append(f"msgid has {len(fuzzy_candidates)} fuzzy-flagged occurrences, ambiguous: {msgid!r}")
            continue
        entry = fuzzy_candidates[0]
        new_line = 'msgstr "' + po_escape(msgstr) + '"'
        edits.append((entry["msgstr_start"], entry["msgstr_end"], [new_line], entry["flag_line_idx"]))
        applied += 1

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)

    # Apply every mutation (msgstr replacements AND flag-line fixes) in a single
    # pass ordered by descending original position. This is the standard
    # "patch back-to-front" invariant: a mutation at position P only shifts
    # indices >= P, so as long as every remaining not-yet-applied edit has a
    # smaller original position than P, its recorded index stays valid right
    # up until it's its turn. Splitting msgstr edits and flag-line edits into
    # two separate passes (fixing all msgstr first, then revisiting flag_line_idx
    # afterwards) breaks this: flag_line_idx is always *before* its own entry's
    # msgstr, but an *earlier* entry's msgstr shrinking shifts every index after
    # it -- including later entries' already-recorded flag_line_idx.
    raw_edits = []
    for msgstr_start, msgstr_end, new_lines, flag_line_idx in edits:
        raw_edits.append((msgstr_start, "msgstr", msgstr_end, new_lines))
        if flag_line_idx is not None:
            raw_edits.append((flag_line_idx, "flag", None, None))
    raw_edits.sort(key=lambda t: t[0], reverse=True)

    for pos, kind, msgstr_end, new_lines in raw_edits:
        if kind == "msgstr":
            lines[pos:msgstr_end] = new_lines
        else:
            line = lines[pos]
            prefix, _, flag_list = line.partition("#,")
            flags = [f.strip() for f in flag_list.split(",") if f.strip() and f.strip() != "fuzzy"]
            if flags:
                lines[pos] = "#, " + ", ".join(flags)
            else:
                del lines[pos]

    new_raw = "\n".join(lines) + ("\n" if trailing_newline else "")
    with open(po_path, "w", encoding="utf-8") as f:
        f.write(new_raw)

    # re-parse to confirm the file is still well-formed and edits landed
    reparsed = polib.pofile(po_path)
    by_msgid_after = {e.msgid: e for e in reparsed}
    for fix in fixes:
        msgid = fix["msgid"]
        e = by_msgid_after.get(msgid)
        if e is None:
            errors.append(f"post-check: msgid missing after edit: {msgid!r}")
        elif "fuzzy" in e.flags:
            errors.append(f"post-check: msgid still fuzzy after edit: {msgid!r}")
        elif e.msgstr != fix["msgstr"]:
            errors.append(f"post-check: msgstr mismatch after edit for {msgid!r}")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)

    print(f"{args.locale}: applied {applied}/{len(fixes)} fixes, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
