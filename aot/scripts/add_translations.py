#!/usr/bin/env python3
# coding=utf-8
"""번역 문구를 안전하게 추가한다 (기존 항목은 건드리지 않는다).

## 왜 스크립트인가

`.po` 에 항목을 손으로 덧붙이다 **같은 msgid 를 두 벌 만든 적이 있다**
(2026-08-19). 긴 문구는 babel 이 여러 줄로 접어 저장하는데

    msgid ""
    "Could not save a server schedule. Turn on at the chosen time using this "
    "browser tab instead? ..."

`msgid "전체 한 줄"` 로 존재 여부를 찾으면 이것을 **못 본다.** 그대로 덧붙이면
중복이 생기고, 컴파일러와 검사기가 서로 다른 항목을 골라 "불일치" 로 뜬다.

여기서는 항상 **접힌 형태를 펴서** 비교한다.

사용:
    python3 aot/scripts/add_translations.py ko additions.json
    # additions.json = {"msgid": "번역문", ...}
    python3 aot/scripts/add_translations.py --check ko    # 중복 msgid 검사
"""
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TR = os.path.join(_ROOT, 'aot_flask', 'translations')


def _po_path(lang):
    return os.path.join(_TR, lang, 'LC_MESSAGES', 'messages.po')


def existing_msgids(src):
    """`.po` 안의 msgid 전부 — **여러 줄로 접힌 것도 편다.**"""
    out, i, lines = set(), 0, src.split('\n')
    while i < len(lines):
        line = lines[i]
        if not line.startswith('msgid '):
            i += 1
            continue
        parts = [line[len('msgid '):].strip()]
        i += 1
        while i < len(lines) and lines[i].startswith('"'):
            parts.append(lines[i].strip())
            i += 1
        joined = ''.join(p[1:-1] for p in parts if len(p) >= 2)
        out.add(joined)
    return out


def check(lang):
    src = open(_po_path(lang), encoding='utf-8').read()
    seen, dupes = set(), []
    for mid in _iter_msgids(src):
        if mid in seen:
            dupes.append(mid)
        seen.add(mid)
    if dupes:
        print('[%s] 중복 msgid %d건:' % (lang, len(dupes)))
        for d in dupes:
            print('  -', d[:70])
        return 1
    print('[%s] 중복 없음 (msgid %d개)' % (lang, len(seen)))
    return 0


def _iter_msgids(src):
    i, lines = 0, src.split('\n')
    while i < len(lines):
        if not lines[i].startswith('msgid '):
            i += 1
            continue
        parts = [lines[i][len('msgid '):].strip()]
        i += 1
        while i < len(lines) and lines[i].startswith('"'):
            parts.append(lines[i].strip())
            i += 1
        yield ''.join(p[1:-1] for p in parts if len(p) >= 2)


def _esc(text):
    return text.replace('\\', '\\\\').replace('"', '\\"')


def add(lang, items):
    path = _po_path(lang)
    src = open(path, encoding='utf-8').read()
    have = existing_msgids(src)
    added, skipped = [], []
    chunks = []
    for mid, mstr in items.items():
        if _esc(mid) in have or mid in have:
            skipped.append(mid)
            continue
        chunks.append('\nmsgid "%s"\nmsgstr "%s"\n' % (_esc(mid), _esc(mstr)))
        added.append(mid)
    if chunks:
        open(path, 'w', encoding='utf-8').write(
            src.rstrip('\n') + '\n' + ''.join(chunks))
    print('[%s] 추가 %d · 건너뜀(이미 있음) %d' % (lang, len(added), len(skipped)))
    for m in skipped:
        print('   · 이미 있음:', m[:64])
    return 0


def main():
    if '--check' in sys.argv:
        langs = [a for a in sys.argv[1:] if not a.startswith('-')]
        return max(check(l) for l in (langs or ['ko', 'ja']))
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    lang, src = sys.argv[1], sys.argv[2]
    return add(lang, json.load(open(src, encoding='utf-8')))


if __name__ == '__main__':
    sys.exit(main())
