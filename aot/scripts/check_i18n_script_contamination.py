#!/usr/bin/env python3
# coding=utf-8
"""번역 카탈로그 문자 오염 검사 — msgstr 에 그 언어에 있을 수 없는 문자가 섞였는지 잡는다.

2026-09-06, 일본어 매뉴얼 작업 중 `ja/LC_MESSAGES/messages.po` 의 msgstr 21건에서
한글 음절이 발견됐다. "酸化還元電위"(電位가 맞음), "日사量"(日射量가 맞음),
"デュー티サイクル"(デューティサイクル가 맞음) 처럼 글자 단위로 한자·가나 한
글자가 한글 한 글자로 바뀐 형태 — 과거 어떤 일괄 치환(번역 재추출/유사문자열
치환 등)이 오작동한 흔적으로 보인다. 같은 방식으로 de(1건 "Systemänderungen"
안에 낀 "등"), es(1건 "control" 안에 낀 "控制")에서도 발견됐다.

이 검사는 그 재발을 잡는다: 언어마다 "그 언어의 고유 문자 체계"를 정의해 두고,
msgstr 에서 그 체계에 속하지 않는 한글/가나/한자/타이문자/데바나가리/키릴 문자가
나오면 의심한다. 다만 전부가 오류는 아니다 — 예를 들어 "무=radish, 배추=cabbage"
처럼 한국어 예시를 의도적으로 든 문자열이나 "[AI 정리 — 미확인]" 같은 리터럴
태그는 msgid 자체에도 같은 문자가 있다. 그래서 **msgstr 의 문자가 msgid 에도
있으면 의도된 것으로 보고 넘어간다** — 글자 단위 차집합이라 오탐이 거의 없다
(실측: 수정 후 22개 언어 전체에서 오탐 0건, 수정 전 실제 오염 23건 전부 검출).

이 검사는 어휘 오역(뜻이 틀린 번역)은 잡지 못한다 — 오직 "이 언어 화면에 나올 수
없는 문자가 섞였는가"만 본다. `.po` 소스 주석(`#`, `#:`)은 대상이 아니다(polib 가
msgid/msgstr 만 본다) — 이 저장소에는 한국어로 적은 설계 문서 참조 주석이 여럿
있고(`# 그룹 스코프 (docs/design/access-scope-groups.md)` 등), 그건 오염이 아니다.

사용:
    python3 aot/scripts/check_i18n_script_contamination.py            # 전체 22개 언어
    python3 aot/scripts/check_i18n_script_contamination.py --locale ja
    python3 aot/scripts/check_i18n_script_contamination.py --json

종료 코드: 0 = 깨끗함 · 1 = 의심 문자열 발견
"""
import argparse
import glob
import json
import os
import sys

import polib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRANSLATIONS_DIR = os.path.join(ROOT, "aot", "aot_flask", "translations")

#: 언어마다 있을 수 없는 문자를 판별하기 위한 문자 체계 범위(대략).
#: 라틴 문자 계열 언어(de/es/fr/hu/id/it/lt/nl/nn/pl/pt/sv/tr 등)는 별도로
#: 자기 문자 체계를 등록하지 않는다 — 아래 SCRIPTS 에 없는 라틴 문자는 애초에
#: 금지 대상이 아니므로 그것으로 충분하다.
SCRIPTS = {
    "HANGUL": [(0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F)],
    "HIRAGANA": [(0x3040, 0x309F)],
    "KATAKANA": [(0x30A0, 0x30FF)],
    "HAN": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)],
    "THAI": [(0x0E00, 0x0E7F)],
    "DEVANAGARI": [(0x0900, 0x097F)],
    "CYRILLIC": [(0x0400, 0x04FF)],
}

#: 언어별 "고유 문자 체계" — 여기 등록된 체계는 그 언어에서 금지하지 않는다.
#: 목록에 없는 언어(라틴 문자 계열)는 SCRIPTS 전부가 금지 대상이 된다.
NATIVE_SCRIPTS = {
    "ko": {"HANGUL"},
    "ja": {"HIRAGANA", "KATAKANA", "HAN"},
    "zh": {"HAN"},
    "zh_Hant": {"HAN"},
    "th": {"THAI"},
    "hi": {"DEVANAGARI"},
    "ru": {"CYRILLIC"},
    "uk": {"CYRILLIC"},
    "sr": {"CYRILLIC"},
}

_MAX_SAMPLES = 20


def _script_of(ch):
    cp = ord(ch)
    for name, ranges in SCRIPTS.items():
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return name
    return None


def check_po(path, locale):
    """의심 항목 목록: [(msgid 축약, msgstr 축약, 문제 문자체계, 문제 글자)]."""
    forbidden = set(SCRIPTS) - NATIVE_SCRIPTS.get(locale, set())
    if not forbidden:
        return []

    po = polib.pofile(path)
    findings = []
    for entry in po:
        msgstrs = [entry.msgstr] + list(getattr(entry, "msgstr_plural", {}).values())
        msgid_chars = set(entry.msgid) | set(entry.msgid_plural or "")
        for msgstr in msgstrs:
            if not msgstr:
                continue
            for ch in msgstr:
                script = _script_of(ch)
                if script and script in forbidden and ch not in msgid_chars:
                    findings.append((entry.msgid[:60], msgstr[:60], script, ch))
                    break
    return findings


def _locales():
    return sorted(
        os.path.basename(os.path.dirname(os.path.dirname(p)))
        for p in glob.glob(os.path.join(TRANSLATIONS_DIR, "*", "LC_MESSAGES", "messages.po"))
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--locale", action="append", help="특정 언어만 검사(반복 가능)")
    parser.add_argument("--json", action="store_true", help="기계 판독 출력")
    args = parser.parse_args()

    locales = args.locale if args.locale else _locales()

    results = []
    total = 0
    for locale in locales:
        po_path = os.path.join(TRANSLATIONS_DIR, locale, "LC_MESSAGES", "messages.po")
        if not os.path.exists(po_path):
            continue
        findings = check_po(po_path, locale)
        if findings:
            results.append({"locale": locale, "count": len(findings), "samples": findings})
            total += len(findings)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1 if total else 0

    for row in results:
        rel = os.path.relpath(
            os.path.join(TRANSLATIONS_DIR, row["locale"], "LC_MESSAGES", "messages.po"), ROOT)
        print("{}: {}건".format(rel, row["count"]))
        for msgid, msgstr, script, ch in row["samples"][:_MAX_SAMPLES]:
            print("   msgid {!r}".format(msgid))
            print("   msgstr {!r}  <- {} 문자 {!r} 가 섞임".format(msgstr, script, ch))
        if row["count"] > _MAX_SAMPLES:
            print("   ... 외 {}건 더".format(row["count"] - _MAX_SAMPLES))

    if total:
        print("\n{}개 언어에서 문자 오염 의심 {}건. 그 언어에 있을 수 없는 문자(한글/가나/한자/"
              "타이문자/데바나가리/키릴)가 msgstr 에 섞여 있고, msgid 에는 같은 문자가 없다 "
              "— 화면에 그대로 노출된다.".format(len(results), total))
        print("의도된 것(예: 한국어 예시 단어, [AI 정리 — 미확인] 같은 리터럴 태그)은 msgid 에도 "
              "같은 문자가 있어야 자동으로 제외된다 — 그래도 걸렸다면 실제 오염이다.")
        return 1

    print("OK: {}개 언어 — msgstr 에 이질적 문자 없음.".format(len(locales)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
