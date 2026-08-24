# coding=utf-8
"""
reference_table_service.py — 표를 '조회할 수 있는 것' 으로 등록한다.

## 왜 지식 항목이 아니라 도구인가

라이브러리는 원래 문서를 잘라 **지식 항목**으로 넣는다. 그런데 행이 수천 개인
참조표(작물 요구조건, 부품 제원, 품종 목록)를 그렇게 넣으면 두 가지가 깨진다.

1. **관련도 오염.** 모든 행이 비슷한 낱말을 담고 있어 매 질의에서 매뉴얼과 경쟁한다.
   실측(2026-08-24, ECOCROP 2,568종): 검색 14ms → 73ms 로 느려지는 것보다, 엉뚱한
   행이 답의 근거로 실리는 쪽이 문제다.
2. **미리 고른 것만 답할 수 있다.** 오염을 피하려고 일부만 적재하면, 표의 값어치
   절반인 "아직 안 다루는 것도 찾아볼 수 있다" 가 죽는다.

그래서 표는 **적재하지 않고 등록만** 한다. 등록할 때 "이 표가 무엇에 답할 수
있는가" 를 함께 받아, AI 에게는 그 설명만 보인다. 그런 요구가 왔을 때만 조회한다.
평소 검색은 조금도 무거워지지 않고, 표 전체가 답변 범위에 들어온다.

## 무엇을 저장하는가

행을 DB 에 넣지 않는다. 파일 한 벌을 `AOT_LOCAL_DIR/reference_tables/` 에 받아
두고 조회 시점에 읽는다(mtime 기준 프로세스 캐시). 마이그레이션이 필요 없고,
표를 바꾸면 파일만 갈리면 된다. 조회는 사람이 물어볼 때만 일어나므로 매 요청
비용이 아니다.
"""
import csv
import io
import logging
import os
import threading

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 60
_MAX_BYTES = 32 * 1024 * 1024      # 32MB — 참조표이지 데이터레이크가 아니다
_MAX_MATCHES = 20                  # 한 번에 돌려줄 행 수 상한
_PREVIEW_COLS = 12                 # 설명에 보일 컬럼 수

_cache = {}                        # path -> (mtime, header, rows)
_cache_lock = threading.Lock()

_ENCODINGS = ('utf-8-sig', 'utf-8', 'cp949', 'cp1252', 'latin-1')


def storage_dir():
    base = os.environ.get('AOT_LOCAL_DIR') or '/app/aot_local'
    path = os.path.join(base, 'reference_tables')
    os.makedirs(path, exist_ok=True)
    return path


def table_path(source_id):
    return os.path.join(storage_dir(), '%s.csv' % source_id)


def _decode(raw):
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _sniff(text):
    """구분자를 추정한다. 쉼표만 가정하면 탭·세미콜론 표를 한 컬럼으로 읽는다."""
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
    except csv.Error:
        return ','


def load(source_id):
    """(header, rows) 를 돌려준다. 파일이 바뀌지 않았으면 다시 읽지 않는다."""
    path = table_path(source_id)
    if not os.path.exists(path):
        return [], []
    mtime = os.path.getmtime(path)
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
    with open(path, 'rb') as fh:
        text = _decode(fh.read())
    reader = csv.DictReader(io.StringIO(text), delimiter=_sniff(text))
    rows = list(reader)
    header = list(reader.fieldnames or [])
    with _cache_lock:
        _cache[path] = (mtime, header, rows)
    return header, rows


# @ANCHOR: REFERENCE_TABLE_FETCH
def fetch(source_id, url):
    """표를 내려받아 저장한다. 성공하면 (rows, cols, None), 실패하면 (0,0,error)."""
    if not (url or '').strip():
        return 0, 0, 'data_url is required.'
    try:
        resp = requests.get(url, timeout=_TIMEOUT, stream=True)
        resp.raise_for_status()
        chunks, total = [], 0
        for chunk in resp.iter_content(65536):
            total += len(chunk)
            if total > _MAX_BYTES:
                return 0, 0, ('표가 너무 큽니다 (%dMB 초과) — 참조표로 쓰기엔 '
                              '지나치게 큽니다.' % (_MAX_BYTES // 1024 // 1024))
            chunks.append(chunk)
        raw = b''.join(chunks)
    except requests.RequestException as exc:
        return 0, 0, '표를 받지 못했습니다: %s' % exc

    text = _decode(raw)
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=_sniff(text))
        rows = list(reader)
        header = list(reader.fieldnames or [])
    except (csv.Error, ValueError) as exc:
        return 0, 0, '표를 읽지 못했습니다 (CSV 가 맞는지 확인하세요): %s' % exc
    if not header:
        return 0, 0, '머리글 행을 찾지 못했습니다 — 첫 줄이 컬럼 이름이어야 합니다.'
    if not rows:
        return 0, 0, '표에 행이 없습니다.'

    path = table_path(source_id)
    tmp = path + '.part'
    with open(tmp, 'wb') as fh:
        fh.write(raw)
    os.replace(tmp, path)          # 반쯤 쓰인 파일이 조회에 잡히지 않게
    with _cache_lock:
        _cache.pop(path, None)
    return len(rows), len(header), None


def describe(source, config):
    """AI 에게 보일 표 소개. **운영자가 적은 설명이 그대로 간다** — 이 표가
    무엇에 답할 수 있는지는 표를 등록한 사람만 안다."""
    header, rows = load(source.source_id)
    return {
        'table_id': source.source_id,
        'title': (config.get('title') or source.source_name or '').strip(),
        'answers': (config.get('answers') or '').strip(),
        'columns': header[:_PREVIEW_COLS],
        'column_count': len(header),
        'row_count': len(rows),
        'search_columns': _search_columns(config, header),
        'attribution': (config.get('attribution') or '').strip(),
        'source_url': (config.get('source_url') or '').strip(),
        'caveat': (config.get('caveat') or '').strip(),
        # AI 가 "어떤 이름으로 물어야 하는가" 를 알 수 있게 함께 낸다.
        'aliases': parse_aliases(config.get('aliases')),
        'name_language': (config.get('name_language') or '').strip(),
    }


# @ANCHOR: REFERENCE_TABLE_ALIASES
def parse_aliases(raw):
    """'무=radish, 배추=cabbage' → {'무': 'radish', '배추': 'cabbage'}.

    왜 필요한가(2026-08-24 실측). ECOCROP 의 통용명 컬럼에는 **한글이 한 건도
    없다.** 그래서 '김장용 무는 어떻게 키워?' 라고 물으면 표에 0건이 걸리고,
    'radish' 로 물어야만 5건이 나온다. 지금은 AI 가 '무 = radish' 를 스스로
    떠올려 영어로 조회해 주기를 기대하는 셈인데, 실측에서 그러지 않았다 —
    모델 재량에 맡기는 방식은 이 시스템이 계속 고쳐 온 실패 형태다.

    별칭은 그 판단을 **표를 등록한 사람**에게 돌려준다. 운영자가 자기 말로
    이름을 붙이면 22개 언어 어디서나 통하고, 원본 표는 건드리지 않는다."""
    out = {}
    for part in (raw or '').replace('\n', ',').split(','):
        if '=' not in part:
            continue
        k, _, v = part.partition('=')
        k, v = k.strip().lower(), v.strip()
        if k and v:
            out[k] = v
    return out


def _search_columns(config, header):
    """어느 컬럼을 이름으로 보고 찾을 것인가. 지정이 없으면 앞쪽 문자열 컬럼을
    쓴다 — 대개 첫 컬럼들이 식별자다."""
    raw = (config.get('search_columns') or '').strip()
    if raw:
        wanted = [c.strip() for c in raw.split(',') if c.strip()]
        cols = [c for c in wanted if c in header]
        if cols:
            return cols
    return header[:3]


def _project(row, columns, header):
    """필요한 컬럼만 남긴다.

    왜 필요한가(2026-08-24 실측). ECOCROP 한 행은 41컬럼 1,152자(~380토큰)인데
    "이 작물 온도 범위가 어떻게 돼?" 가 필요로 하는 건 서넛뿐이다. 5행을 돌려주면
    6,637자(~2,200토큰)를 쓰고, 그중 대부분은 모델이 읽지도 않을 값이다.

    행 수는 이미 세 겹으로 막혀 있다(limit 상한, 엔진의 도구결과 상한, 그리고
    전량 덤프 오퍼레이션이 아예 없다는 것). 남은 낭비는 **폭**이라 여기서 줄인다.
    전체가 필요하면 호출자가 columns 로 명시하거나 '*' 를 준다."""
    if not columns:
        return row
    if '*' in columns:
        return row
    keep = [c for c in columns if c in header]
    if not keep:
        return row
    return {k: v for k, v in row.items() if k in keep}


def query(source, config, text, limit=5, columns=None):
    """이름으로 행을 찾는다. 반환은 행 dict 목록.

    낱말 단위로 본다 — 부분 일치만 쓰면 'rice' 가 'ricefield weed' 를 물어 온다."""
    header, rows = load(source.source_id)
    if not rows:
        return [], '표가 아직 내려받아지지 않았습니다 — 소스를 동기화하세요.'
    needle = (text or '').strip().lower()
    if not needle:
        return [], 'query is required.'
    # 별칭 먼저. 정확히 일치할 때만 바꾼다 — 부분 치환은 '무름병' 을 'radish병'
    # 으로 만든다.
    aliases = parse_aliases(config.get('aliases'))
    if needle in aliases:
        needle = aliases[needle].strip().lower()
    cols = _search_columns(config, header)
    try:
        limit = max(1, min(int(limit), _MAX_MATCHES))
    except (TypeError, ValueError):
        limit = 5

    # 순위가 셋이다. 실측(2026-08-24)으로 필요해진 구분: 'tomato' 로 찾으면
    # 'tree tomato'(Cyphomandra betacea)가 진짜 토마토(Lycopersicon esculentum)
    # 보다 먼저 나왔다 — 낱말 매치를 이름 전체 매치와 같이 취급했기 때문이다.
    #   1) 이름 하나와 **통째로** 같다      'tomato' == 'tomato'
    #   2) 칸 전체와 같다                  학명 칸처럼 이름이 하나뿐일 때
    #   3) 이름 안의 낱말로 걸린다          'tree tomato' 의 'tomato'
    whole, cellwise, wordwise = [], [], []
    for row in rows:
        bucket = None
        for col in cols:
            cell = (row.get(col) or '').strip().lower()
            if not cell:
                continue
            names = [n.strip() for n in cell.split(',') if n.strip()]
            if needle in names:
                bucket = whole
                break
            if cell == needle:
                bucket = cellwise
                break
            if any(needle in n.split() for n in names):
                bucket = bucket or wordwise
        if bucket is not None:
            bucket.append(row)
            if len(whole) >= limit:
                break
    ranked = whole + cellwise + wordwise
    found = ranked[:limit]
    # 투영은 호출자 지정이 우선, 없으면 운영자가 정한 기본값, 그것도 없으면 전체.
    cols = columns
    if not cols:
        raw = (config.get('summary_columns') or '').strip()
        cols = [c.strip() for c in raw.split(',') if c.strip()] if raw else None
    return [_project(_clean(r), cols, header) for r in found], None


def _clean(row):
    """빈 칸과 'NA' 를 지운다 — 모델에게 빈 값을 잔뜩 보내면 그걸 사실로 읽는다."""
    return {k: v for k, v in row.items()
            if k and v is not None and str(v).strip() and str(v).strip().upper() != 'NA'}
