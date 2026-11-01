# coding=utf-8
"""이름 비교용 열쇠 — 표기만 다른 같은 이름을 한 값으로 모은다.

"온습도 7" · "온습도_7" · "온습도7" · "온습도－７"(전각) · "ON습도 7" 이 같은 열쇠가 된다.
소문자(casefold)·NFKC(전각→반각)·공백/밑줄/가운뎃점 제거. 하이픈은 지우되 **숫자 사이의
하이픈은 남긴다** — 구역 '3-1' 과 '31' 이 같은 이름이 되면 안 된다.
철자가 다른 이름(음성 오인식, 번역)은 맞추지 않는다: 열쇠가 같을 때만 같은 이름이다.
"""
import re
import unicodedata

_SEP = re.compile(r'[\s_·・‐-―−]+')
_HYPHEN = re.compile(r'(?<!\d)-|-(?!\d)')


def name_key(text):
    s = unicodedata.normalize('NFKC', str(text or '')).casefold()
    s = _SEP.sub(lambda m: '-' if re.search(r'[-‐-―−]', m.group()) else '', s)
    return _HYPHEN.sub('', s)
