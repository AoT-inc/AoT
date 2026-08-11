#!/usr/bin/env python3
# coding=utf-8
"""번역 카탈로그 드리프트 검사 — `.po` 를 고치고 `.mo` 재컴파일을 빠뜨린 것을 잡는다.

앱이 실제로 읽는 것은 **`.mo`(바이너리)** 다. `.po` 만 고치고 `pybabel compile` 을
빠뜨리면 아무 에러도 나지 않고, 테스트도 통과하고, 리뷰에서도 안 보인다 —
`.mo` 는 바이너리라 diff 에 내용이 드러나지 않기 때문이다. 그 사이 그 언어
사용자는 **번역이 있는데도 영어를 본다.** JS 번들 드리프트(`check_js_bundles.py`)
와 정확히 같은 종류의 조용한 실패다.

실제로 그 상태였다: 2026-08-11 무관한 작업 중 `pybabel compile` 을 돌리자 손대지
않은 18개 언어의 `.mo` 가 함께 바뀌었다 — de 157KB → 217KB 처럼 40% 가까이.
저장소의 `.mo` 가 자기 `.po` 보다 그만큼 뒤처져 있었다는 뜻이고, 언제부터인지는
아무도 모른다.

**바이트 비교가 아니라 의미 비교를 한다.** 컴파일러(babel/msgfmt) 버전이 다르면
같은 `.po` 에서도 바이트가 달라질 수 있어, 바이트로 보면 정상 커밋을 계속
드리프트로 올린다(`check_js_bundles.py --history` 가 겪는 문제와 같다). 여기서는
양쪽에서 메시지 카탈로그를 뽑아 **키와 번역문을 대조**한다.

msgfmt 의 규칙을 그대로 흉내 낸다 — `.mo` 에 들어가는 항목은:
  - `msgstr` 이 비어 있지 않고
  - `#, fuzzy` 가 아니고 (기본값에서 fuzzy 는 제외된다)
  - 폐기 항목(`#~`)이 아닌 것

**`pybabel compile -f` 를 쓰지 말 것.** `-f` 는 `--force` 가 아니라 `--use-fuzzy`
다 — 미검토 fuzzy 번역까지 `.mo` 에 넣는다. 2026-08-11 그렇게 컴파일해 18개
언어에 1256건씩(es 는 195건) 주입했고, `.mo` 가 40% 커진 것을 "원래 스테일했다"
로 오진할 뻔했다. 이 검사가 그 커밋을 잡아냈다 — fuzzy 를 제외하는 이 파서와
fuzzy 를 포함한 `.mo` 사이의 차이가 정확히 그 건수로 드러났기 때문이다.

헤더(`msgid ""`)는 비교에서 뺀다 — 컴파일 과정에서 일부 필드가 정규화될 수 있어
드리프트가 아닌 차이를 만든다.

표준 라이브러리만 쓴다. babel 이 없어도, 설치가 깨져도 돌아야 한다.

사용:
    python3 aot/scripts/check_po_mo_sync.py            # 워킹트리
    python3 aot/scripts/check_po_mo_sync.py --staged   # 인덱스 (pre-commit 훅)
    python3 aot/scripts/check_po_mo_sync.py --json     # 기계 판독
    python3 aot/scripts/check_po_mo_sync.py --quiet    # 요약만

종료 코드: 0 = 일치 · 1 = 드리프트 · 2 = 검사 실패
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TRANSLATIONS = os.path.join('aot', 'aot_flask', 'translations')

#: 한 언어에서 보고할 불일치 항목의 최대 수. 전부 쏟아내면 진짜 원인이 묻힌다.
_MAX_SAMPLES = 5


# ---------------------------------------------------------------------------
# 파일 읽기 — 워킹트리 / 인덱스
# ---------------------------------------------------------------------------

def _git(args):
    return subprocess.run(['git'] + args, cwd=ROOT,
                          capture_output=True)


def _read_worktree(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return None
    with open(full, 'rb') as handle:
        return handle.read()


def _read_index(path):
    """인덱스(스테이지)에 있는 내용. 스테이지에 없으면 HEAD 것으로 떨어진다.

    **인덱스를 봐야 하는 이유**: 워킹트리를 보면 ".po 만 stage 하고 .mo 는 컴파일만
    해 두고 stage 하지 않은" 커밋이 통과한다 — 그게 정확히 막으려는 경우다.
    """
    out = _git(['show', ':' + path])
    if out.returncode == 0:
        return out.stdout
    out = _git(['show', 'HEAD:' + path])
    return out.stdout if out.returncode == 0 else None


def _list_languages(staged=False):
    """(언어코드, po경로, mo경로) 목록."""
    langs = []
    if staged:
        out = _git(['ls-files', TRANSLATIONS])
        names = out.stdout.decode('utf-8', 'replace').splitlines()
        codes = sorted({n.split('/')[3] for n in names
                        if n.endswith('LC_MESSAGES/messages.po')})
    else:
        base = os.path.join(ROOT, TRANSLATIONS)
        if not os.path.isdir(base):
            return langs
        codes = sorted(d for d in os.listdir(base)
                       if os.path.isfile(os.path.join(
                           base, d, 'LC_MESSAGES', 'messages.po')))
    for code in codes:
        langs.append((
            code,
            '{}/{}/LC_MESSAGES/messages.po'.format(TRANSLATIONS, code),
            '{}/{}/LC_MESSAGES/messages.mo'.format(TRANSLATIONS, code)))
    return langs


# ---------------------------------------------------------------------------
# .po 파싱 — msgfmt 의 포함 규칙을 그대로 따른다
# ---------------------------------------------------------------------------

_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unquote(line):
    """행에 들어 있는 따옴표 문자열들을 이어 붙여 디코드한다."""
    parts = _STRING.findall(line)
    if not parts:
        return ''
    raw = ''.join(parts)
    # .po 의 이스케이프는 C 규약이다.
    return (raw.replace('\\n', '\n').replace('\\t', '\t')
               .replace('\\r', '\r').replace('\\"', '"')
               .replace('\\\\', '\\'))


def _parse_block(block):
    """`.po` 항목 하나(빈 줄로 구분된 블록) → (키, {인덱스: 번역문}, fuzzy) 또는 None.

    gettext 계열 도구는 항목 사이에 항상 빈 줄을 넣는다. 블록으로 자르면 "지금
    어떤 항목을 읽는 중인가" 를 들고 다닐 필요가 없어져 상태 처리가 사라진다.
    """
    ctxt = msgid = None
    msgstrs = {}
    fuzzy = False
    field = None          # 'ctxt' | 'id' | 'plural' | ('str', 인덱스)
    has_plural = False

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('#~'):                 # 폐기 항목 — .mo 에 안 들어간다
            return None
        if line.startswith('#'):
            if line.startswith('#,') and 'fuzzy' in line:
                fuzzy = True
            continue

        if line.startswith('msgctxt'):
            ctxt = _unquote(line)
            field = 'ctxt'
        elif line.startswith('msgid_plural'):
            has_plural = True
            field = 'plural'
        elif line.startswith('msgid'):
            msgid = _unquote(line)
            field = 'id'
        elif line.startswith('msgstr'):
            index = 0
            if line.startswith('msgstr['):
                try:
                    index = int(line[7:line.index(']')])
                except (ValueError, IndexError):
                    index = 0
            msgstrs[index] = _unquote(line)
            field = ('str', index)
        elif line.startswith('"'):                # 여러 줄 문자열의 이어지는 행
            chunk = _unquote(line)
            if field == 'ctxt':
                ctxt = (ctxt or '') + chunk
            elif field == 'id':
                msgid = (msgid or '') + chunk
            elif isinstance(field, tuple):
                msgstrs[field[1]] = msgstrs.get(field[1], '') + chunk
            # 'plural' 의 이어지는 행은 키에 쓰이지 않으므로 버린다.

    if msgid is None:
        return None
    key = msgid if ctxt is None else '{}\x04{}'.format(ctxt, msgid)
    return key, msgstrs, fuzzy, has_plural


def parse_po(data):
    """`.po` 바이트 → {키: 번역문}. msgfmt 가 `.mo` 에 넣을 것만 담는다.

    키 규약은 gettext 카탈로그와 같다:
      - 문맥 없음/단수 : msgid
      - 문맥 있음      : "문맥\\x04msgid"
      - 복수           : (키, 인덱스)
    """
    text = data.decode('utf-8', 'replace')
    catalog = {}

    for block in re.split(r'\n[ \t]*\n', text):
        parsed = _parse_block(block)
        if parsed is None:
            continue
        key, msgstrs, fuzzy, has_plural = parsed
        if fuzzy or key == '':            # fuzzy 는 기본값에서 제외, 헤더는 비교 안 함
            continue

        if not has_plural:
            value = msgstrs.get(0, '')
            if value:                     # 빈 번역은 .mo 에 들어가지 않는다
                catalog[key] = value
            continue

        # 복수형 — 하나라도 비어 있으면 msgfmt 가 그 항목을 통째로 건너뛴다.
        indexes = sorted(msgstrs)
        if indexes and all(msgstrs[i] for i in indexes):
            for i in indexes:
                catalog[(key, i)] = msgstrs[i]

    return catalog


# ---------------------------------------------------------------------------
# .mo 파싱 — gettext 와 같은 카탈로그를 만든다(표준 라이브러리 구현을 따름)
# ---------------------------------------------------------------------------

def parse_mo(data):
    """`.mo` 바이트 → {키: 번역문}. 형식이 아니면 ValueError."""
    if len(data) < 20:
        raise ValueError("파일이 너무 짧습니다")
    magic = struct.unpack('<I', data[:4])[0]
    if magic == 0x950412de:
        endian = '<'
    elif magic == 0xde120495:
        endian = '>'
    else:
        raise ValueError("매직 넘버가 .mo 가 아닙니다")

    _version, count, origin, translation = struct.unpack(
        endian + '4I', data[4:20])

    catalog = {}
    for i in range(count):
        o_len, o_off = struct.unpack(endian + '2I', data[origin + i * 8:origin + i * 8 + 8])
        t_len, t_off = struct.unpack(endian + '2I',
                                     data[translation + i * 8:translation + i * 8 + 8])
        msg = data[o_off:o_off + o_len]
        tmsg = data[t_off:t_off + t_len]

        if b'\x00' in msg:                        # 복수형
            singular, _plural = msg.split(b'\x00', 1)
            key = singular.decode('utf-8', 'replace')
            for index, part in enumerate(tmsg.split(b'\x00')):
                catalog[(key, index)] = part.decode('utf-8', 'replace')
        else:
            key = msg.decode('utf-8', 'replace')
            if key == '':                         # 헤더 — 비교 대상 아님
                continue
            catalog[key] = tmsg.decode('utf-8', 'replace')
    return catalog


# ---------------------------------------------------------------------------
# 비교
# ---------------------------------------------------------------------------

def compare(po_catalog, mo_catalog):
    """(누락, 잔존, 불일치) — 각각 키 목록."""
    po_keys = set(po_catalog)
    mo_keys = set(mo_catalog)
    missing = sorted(po_keys - mo_keys, key=str)      # .po 에 있는데 .mo 에 없다
    stale = sorted(mo_keys - po_keys, key=str)        # .mo 에만 남아 있다
    changed = sorted((k for k in po_keys & mo_keys
                      if po_catalog[k] != mo_catalog[k]), key=str)
    return missing, stale, changed


def _label(key):
    if isinstance(key, tuple):
        return '{}[{}]'.format(key[0], key[1])
    return key.replace('\x04', ' / ')


def check(staged=False):
    """(결과 리스트, 종료코드)."""
    read = _read_index if staged else _read_worktree
    results = []
    worst = 0

    languages = _list_languages(staged=staged)
    if not languages:
        return [{"lang": "-", "status": "error",
                 "detail": "번역 디렉터리를 찾지 못했습니다: " + TRANSLATIONS}], 2

    for code, po_path, mo_path in languages:
        po_data = read(po_path)
        mo_data = read(mo_path)

        if po_data is None:
            continue
        if mo_data is None:
            results.append({"lang": code, "status": "missing-mo",
                            "detail": ".mo 파일이 없습니다 — 컴파일이 필요합니다."})
            worst = max(worst, 1)
            continue

        try:
            po_catalog = parse_po(po_data)
            mo_catalog = parse_mo(mo_data)
        except Exception as exc:                     # noqa: BLE001
            results.append({"lang": code, "status": "error",
                            "detail": "파싱 실패: {}".format(exc)})
            worst = max(worst, 2)
            continue

        missing, stale, changed = compare(po_catalog, mo_catalog)
        if missing or stale or changed:
            results.append({
                "lang": code, "status": "drift",
                "po_entries": len(po_catalog), "mo_entries": len(mo_catalog),
                "missing": len(missing), "stale": len(stale), "changed": len(changed),
                "samples": [_label(k) for k in (missing + changed + stale)[:_MAX_SAMPLES]],
            })
            worst = max(worst, 1)
        else:
            results.append({"lang": code, "status": "ok",
                            "po_entries": len(po_catalog)})

    return results, worst


def main():
    parser = argparse.ArgumentParser(
        description=".po 와 .mo 가 어긋났는지 검사한다(재컴파일 누락 탐지).")
    parser.add_argument('--staged', action='store_true',
                        help="워킹트리 대신 인덱스를 본다(pre-commit 훅용)")
    parser.add_argument('--json', action='store_true', help="기계 판독 출력")
    parser.add_argument('--quiet', action='store_true', help="요약만")
    args = parser.parse_args()

    results, code = check(staged=args.staged)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return code

    scope = '인덱스' if args.staged else '워킹트리'
    drifted = [r for r in results if r['status'] in ('drift', 'missing-mo')]
    errors = [r for r in results if r['status'] == 'error']

    if not args.quiet:
        for row in drifted:
            if row['status'] == 'missing-mo':
                print("[{}] {}".format(row['lang'], row['detail']))
                continue
            print("[{}] .po {}건 ↔ .mo {}건 — 누락 {} · 잔존 {} · 불일치 {}".format(
                row['lang'], row['po_entries'], row['mo_entries'],
                row['missing'], row['stale'], row['changed']))
            for sample in row['samples']:
                shown = sample if len(sample) <= 60 else sample[:57] + '...'
                print("      · {}".format(shown))
    for row in errors:
        print("[{}] {}".format(row['lang'], row['detail']))

    if errors:
        print("검사 실패({}).".format(scope))
        return code
    if drifted:
        print("드리프트 {}개 언어({}). `.po` 를 고치고 재컴파일을 빠뜨렸습니다:"
              .format(len(drifted), scope))
        print("  pybabel compile -d aot/aot_flask/translations")
        print("  ※ `-f` 를 붙이지 말 것 — --force 가 아니라 --use-fuzzy 다.")
        print("     붙이면 미검토 fuzzy 번역까지 .mo 에 들어간다"
              "(2026-08-11 실제로 18개 언어에 1256건씩 주입했다).")
        return code

    print("OK: {} 번역 {}개 언어 — .po 와 .mo 가 일치합니다."
          .format(scope, len(results)))
    return code


if __name__ == '__main__':
    sys.exit(main())
