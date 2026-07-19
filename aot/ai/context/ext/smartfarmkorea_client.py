# coding=utf-8
"""
smartfarmkorea_client.py — SmartFarmKorea 빅데이터 제공서비스, THREE datasets:

  EXT-KR-04 시설원예 (facility) — menuId=M1104030101
    https://smartfarmkorea.net/openApi/openApiList.do?menuId=M1104030101
    ~2,300 facility-greenhouse farms. 7 operations (OPERATIONS below).
  EXT-KR-05 노지 (outdoor field)  — menuId=M11040302
    https://smartfarmkorea.net/openApi/openApiList.do?menuId=M11040302
    ~1,650 open-field farms (마늘/양파/블루베리 growth ops implemented on the
    site as of 2026-07-19; page describes 11 crops total — 감귤/감자/배추/대파/
    사과/콩/복숭아/무/포도 have NO dedicated getXCultivateDataList operation
    live yet, only identity/cropping/env cover them). 6 operations
    (OUTDOOR_OPERATIONS below).
  EXT-KR-06 축산 (livestock)     — menuId=M11040303
    https://smartfarmkorea.net/openApi/openApiList.do?menuId=M11040303
    348 farms across 4 species (낙농/양돈/양계/한우). Page states
    "업데이트 주기: 수집종료" — data collection ended (2020-2022), this is a
    frozen historical archive, not a live-growing feed; sync still runs on
    schedule like the other presets (harmless — the date-range query just
    returns the same fixed dataset), but the injected knowledge won't gain
    new records over time. 11 operations (LIVESTOCK_OPERATIONS below).
    Structurally simpler than the other two: every operation takes only
    serviceKey+startDate+endDate — no operator-specific
    userId/facilityId/croppingSerlNo discovery chain (confirmed by reading
    all 11 of the page's own request-parameter tables, not assumed from a
    sample).

Operator (all three): 농림수산식품교육문화정보원 (Ministry-run agricultural
data mart) — a DIFFERENT organization/dataset from RDA's SmartFarm
Productivity API (EXT-KR-01, aot/ai/context/ext/smartfarm_client.py,
api.data.go.kr): RDA publishes curated OPTIMAL setpoint ranges per
crop/stage; SmartFarmKorea publishes raw MEASURED data (environment sensor
readings + growth/production measurements) from real participating farms —
empirical, not prescriptive. All tagged provenance='external_authority'
(§3.1: none need human review), but cited as "실측 데이터" (measured data),
not a recommendation, so the model doesn't conflate the two.

Kept as THREE SEPARATE dicts (not merged into one operation list) because:
  (a) different URL base per dataset (ProvideRestService / OutdoorFarmRest /
      StockRestService) — confirmed via each source page's own data-url
      attributes, not assumed from the naming;
  (b) the site itself presents them as separate OPEN-API catalog entries
      with separate "Open API 신청" (apply) flows, so the service key may
      well differ between them;
  (c) facility/outdoor share 'identity'/'cropping'/'env' operation NAMES
      with DIFFERENT underlying data (different farm population) — merging
      into one flat OPERATIONS dict would silently collide on those keys.
      Separate dicts avoid the collision entirely rather than inventing a
      namespacing scheme. Livestock's operation keys don't collide with the
      other two, but it's kept as its own dict for the same reasons (a)/(b)
      and because its param shape is genuinely different (no discovery
      chain at all — see EXT-KR-06 note above).

All three are **path-segment REST APIs** (params are `/`-joined URL path
components in a fixed order per operation), not query-string — the generic
`rest_api` source type's `_fetch_rest_api()` (query-string GET + header
auth) cannot express it, hence a dedicated client. Every URL below was
confirmed live against the respective page's own "샘플 URL" panel
(2026-07-19).

Facility/outdoor operations need an operator-specific userId/facilityId/
croppingSerlNo the operator must already know (farm-specific historical
data, not a bounded reference table like RDA's crop×stage grid) — except
'identity', which takes only serviceKey and returns EVERY farm the key can
see (confirmed live: a real key returned 2,308 facility-dataset rows) — the
natural discovery step before filling in the other operations' params.
Livestock has no such chain (see EXT-KR-06 note above) — every operation is
independently callable with just a service key and date range. So, unlike
EXT-KR-01/02/03, sync is opt-in PER OPERATION (the Add-source UI's
checklist) and per-operation params come from the operator, not defaults.
"""
import logging

import requests

logger = logging.getLogger(__name__)

_API_BASE_FACILITY = "http://www.smartfarmkorea.net/Agree_WS/webservices/ProvideRestService"
_API_BASE_OUTDOOR = "http://www.smartfarmkorea.net/Agree_WS/webservices/OutdoorFarmRest"
_API_BASE_LIVESTOCK = "http://www.smartfarmkorea.net/Agree_WS/webservices/StockRestService"
_REQUEST_TIMEOUT = 20
_MAX_RECORDS_PER_OP = 50  # digest stays a knowledge summary, not a full data dump

# @ANCHOR: SMARTFARMKOREA_OPERATIONS
# EXT-KR-04 시설원예 (facility greenhouses). param order MUST match the
# source page's path-segment order exactly.
OPERATIONS = {
    'identity': {
        'base': _API_BASE_FACILITY,
        'path': 'getIdentityDataList',
        'category': '아이덴티티',
        'label_ko': '아이덴티티 정보',
        'params': ['serviceKey'],
    },
    'cropping': {
        'base': _API_BASE_FACILITY,
        'path': 'getCroppingSeasonDataList',
        'category': '작기',
        'label_ko': '작기 정보',
        'params': ['serviceKey', 'userId'],
    },
    'env': {
        'base': _API_BASE_FACILITY,
        'path': 'getEnvDataList',
        'category': '환경',
        'label_ko': '환경 정보',
        'params': ['serviceKey', 'facilityId', 'measDate', 'fldCode', 'sectCode', 'fatrCode', 'itemCode'],
    },
    'growth_strawberry': {
        'base': _API_BASE_FACILITY,
        'path': 'getStrbCultivateDataList',
        'category': '생육',
        'label_ko': '생육 정보(딸기)',
        'params': ['serviceKey', 'userId', 'croppingSerlNo', 'startDate', 'endDate'],
    },
    'growth_mum': {
        'base': _API_BASE_FACILITY,
        'path': 'getMumCultivateDataList',
        'category': '생육',
        'label_ko': '생육 정보(국화)',
        'params': ['serviceKey', 'userId', 'croppingSerlNo', 'startDate', 'endDate'],
    },
    'growth_melon': {
        'base': _API_BASE_FACILITY,
        'path': 'getFruitCultivateDataList',
        'category': '생육',
        'label_ko': '생육 정보(참외)',
        'params': ['serviceKey', 'userId', 'croppingSerlNo', 'startDate', 'endDate'],
    },
    'growth_other': {
        'base': _API_BASE_FACILITY,
        'path': 'getCultivateDataList',
        'category': '기타 작물',
        'label_ko': '생육 정보(그외)',
        'params': ['serviceKey', 'userId', 'croppingSerlNo', 'startDate', 'endDate'],
    },
}

# @ANCHOR: SMARTFARMKOREA_OUTDOOR_OPERATIONS
# EXT-KR-05 노지 (open-field farms). Same param shapes as OPERATIONS above
# (identity/cropping/env/growth all follow the identical pattern), different
# base URL and different growth-operation set (마늘/양파/블루베리 only —
# see module docstring on the other 8 listed crops having no live endpoint).
OUTDOOR_OPERATIONS = {
    'identity': {
        'base': _API_BASE_OUTDOOR,
        'path': 'getIdentityDataList',
        'category': '아이덴티티',
        'label_ko': '아이덴티티 정보',
        'params': ['serviceKey'],
    },
    'cropping': {
        'base': _API_BASE_OUTDOOR,
        'path': 'getCroppingSeasonDataList',
        'category': '작기',
        'label_ko': '작기 정보',
        'params': ['serviceKey', 'userId'],
    },
    'env': {
        'base': _API_BASE_OUTDOOR,
        'path': 'getEnvDataList',
        'category': '환경',
        'label_ko': '환경 정보',
        'params': ['serviceKey', 'facilityId', 'measDate', 'fldCode', 'sectCode', 'fatrCode', 'itemCode'],
    },
    'growth_garlic': {
        'base': _API_BASE_OUTDOOR,
        'path': 'getGarlicCultivateDataList',
        'category': '생육',
        'label_ko': '생육 정보(마늘)',
        'params': ['serviceKey', 'userId', 'croppingSerlNo', 'startDate', 'endDate'],
    },
    'growth_onion': {
        'base': _API_BASE_OUTDOOR,
        'path': 'getOnionCultivateDataList',
        'category': '생육',
        'label_ko': '생육 정보(양파)',
        'params': ['serviceKey', 'userId', 'croppingSerlNo', 'startDate', 'endDate'],
    },
    'growth_blueberry': {
        'base': _API_BASE_OUTDOOR,
        'path': 'getBlueberryCultivateDataList',
        'category': '생육',
        'label_ko': '생육 정보(블루베리)',
        'params': ['serviceKey', 'userId', 'croppingSerlNo', 'startDate', 'endDate'],
    },
}

# @ANCHOR: SMARTFARMKOREA_LIVESTOCK_OPERATIONS
# EXT-KR-06 축산 (livestock — 낙농/양돈/양계/한우). Unlike OPERATIONS/
# OUTDOOR_OPERATIONS, every operation here takes the SAME 3 params
# (serviceKey/startDate/endDate) — no userId/facilityId/croppingSerlNo
# discovery chain, confirmed by reading all 11 of the source page's own
# request-parameter tables (2026-07-19).
LIVESTOCK_OPERATIONS = {
    'dairy_inspection': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getInspctDataList',
        'category': '낙농', 'label_ko': '유성분검사성적서 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'dairy_robot_milking': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getMilkingDataList',
        'category': '낙농', 'label_ko': '로봇착유기 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'dairy_ict_milking': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getIctDataList',
        'category': '낙농', 'label_ko': 'ICT착유기 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'dairy_ict_group_feed': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getIctMkFdDataList',
        'category': '낙농', 'label_ko': 'ICT착유기 군사급이기 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'dairy_robot_group_feed': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getRoboMkFdDataList',
        'category': '낙농', 'label_ko': '로봇착유기 착유군사급이기 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'swine_sow': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getSowDataList',
        'category': '양돈', 'label_ko': '모돈 데이터셋 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'swine_lactating_feed': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getMoPigDataList',
        'category': '양돈', 'label_ko': '포유모돈 급이 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'swine_lactating_feed_breeding': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getMoPigFdBrdDataList',
        'category': '양돈', 'label_ko': '포유모돈 급이 번식 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'poultry_daily': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getLayingDataList',
        'category': '양계', 'label_ko': '일일생산 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'hanwoo_epd': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getCowDataList',
        'category': '한우', 'label_ko': 'EPD 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
    'hanwoo_grading': {
        'base': _API_BASE_LIVESTOCK, 'path': 'getShipmntDataList',
        'category': '한우', 'label_ko': '등급판정 정보',
        'params': ['serviceKey', 'startDate', 'endDate'],
    },
}

# Field label translation for the digest text — keeps the injected knowledge
# readable Korean prose instead of a raw JSON dump. Deliberately small/partial:
# unknown fields fall back to their raw key (see _format_record), so this
# doesn't need to be exhaustive to be useful.
_FIELD_LABELS = {
    'userId': '사용자ID', 'facilityId': '시설ID', 'addressName': '지역',
    'itemCode': '품목코드', 'croppingSeasonName': '작기명', 'croppingDate': '작기시작',
    'croppingEndDate': '작기종료', 'croppingSystem': '재배방식코드',
    'cultivationArea': '재배면적(평)', 'calCultivationArea': '재배면적(㎡)',
    'plantNum': '재식수량', 'plantDensity': '재식밀도', 'measDate': '측정일시',
    'fldCode': '분야코드', 'sectCode': '분류코드', 'fatrCode': '항목코드',
    'senVal': '측정값', 'sampleNum': '표본번호', 'leavesNum': '엽수',
    'leavesLength': '엽장(mm)', 'leavesWidth': '엽폭(mm)', 'petioleLength': '엽병장(cm)',
    'thecaDiameter': '관부직경(mm)', 'fruitClusterNum': '화방수', 'stemDiameter': '줄기직경(mm)',
    'flowerLength': '초장(mm)', 'growLength': '생장길이(mm)', 'fruitsWeight': '평균과중(g)',
    'fruitsNum': '열매수',
    # 노지(OUTDOOR_OPERATIONS) 전용 필드 — growth_garlic/growth_onion 등
    'plantLength': '초장(mm)', 'leafNum': '엽수(개)', 'rootDiameter': '구직경(cm)',
    'rootWeight': '구당무게(g)', 'expectHarvest': '예상수량(10a,개)',
    'cropLineDistance': '이랑거리(cm)', 'headsDistance': '작물거리(cm)',
    'headsAvgCount': '평당주수(주)', 'cropHeight': '초장(mm)',
    'suckerNum': '흡지수(개)', 'suckerLength': '흡지길이(cm)', 'soilPh': '토양PH',
}

# growth_blueberry는 fruitWeight1..10 / sugarContent1..10 처럼 필드명에 숫자
# 접미사가 붙어 반복된다 (_FIELD_LABELS의 정확일치 조회로는 못 잡음). 접미사를
# 떼어낸 베이스 키로 재조회하고, 라벨에 번호를 이어붙인다.
_NUM_SUFFIX_FIELD_LABELS = {
    'fruitWeight': '과중(g)', 'sugarContent': '당도(Brix)',
}

# 축산(LIVESTOCK_OPERATIONS) 전용 필드 — 11개 오퍼레이션 중 반복적으로 등장하는
# 항목만 번역(전체 150여개 필드를 다 옮기지 않는 partial 원칙은 _FIELD_LABELS와
# 동일). 'itemCode'는 시설원예/노지에서는 품목(작물)코드지만 축산에서는
# 축종코드로 의미가 달라 전역 사전을 덮어쓰지 않고 별도 사전으로 분리 —
# _format_record가 데이터셋(operations)에 따라 어느 사전을 먼저 조회할지 고른다.
_LIVESTOCK_FIELD_LABELS = {
    'farmId': '농장ID', 'farmCode': '농장ID', 'lsindRegistNo': '축산업 등록번호',
    'itemCode': '축종코드', 'indvdNo': '개체번호', 'indvdNm': '개체명',
    'mesureDt': '측정일시', 'mesureDe': '측정일자', 'admNm': '지역명',
    'lvNm': '사육마릿수', 'breedNm': '품종명', 'parity': '산차수',
    'milkingQy': '착유량', 'milkingTme': '착유횟수', 'conductivity': '전도율',
    'smtcel': '체세포수', 'milkFat': '유지방비율', 'milkProtein': '유단백비율',
    'makrId': '제조사ID', 'eqpmnCode': '장비코드', 'eqpmnNo': '장비번호',
    'colctDe': '수집일자', 'colctCo': '수집건수', 'shipmntDe': '출하일자',
    'carcassWt': '도체중량', 'lastGrad': '최종등급',
}


def _field_label(key, dataset_labels=None):
    if dataset_labels and key in dataset_labels:
        return dataset_labels[key]
    if key in _FIELD_LABELS:
        return _FIELD_LABELS[key]
    for base, label in _NUM_SUFFIX_FIELD_LABELS.items():
        if key.startswith(base) and key[len(base):].isdigit():
            return f"{label}{key[len(base):]}"
    return key


# itemCode → 작물명. itemCode is the national 농산물표준코드 (same meaning across
# all three datasets), but identity/cropping only return the CODE, not the name
# — so "080400" tells neither the operator nor the AI it's 딸기. This map lets
# the farm/season pickers and the AI lookup show/filter by crop NAME instead of
# an opaque code (the earlier footgun: the AI proposed a 토마토 farm for a 딸기
# request because it couldn't tell them apart). DELIBERATELY PARTIAL: only the
# codes VERIFIED across multiple farms' cropping-season names (2026-07-19) are
# here; an unknown code falls back to showing the raw code (same philosophy as
# _FIELD_LABELS). Extend as more codes are confirmed — never guess a mapping,
# a wrong crop label is worse than a raw code.
_ITEM_CODE_CROP = {
    '080400': '딸기', '080300': '토마토', '080600': '방울토마토',
    '080200': '참외', '090100': '오이', '150400': '고추',
    '061400': '감귤', '061500': '만감류', '065900': '블루베리',
}


def crop_name(item_code):
    """작물명 for an itemCode, or the raw code if not in the verified map."""
    code = '' if item_code is None else str(item_code).strip()
    return _ITEM_CODE_CROP.get(code, code)


# preset_key (LIBRARY_PRESETS / config_json) → operations dict. Single source
# of this mapping so callers (sync dispatch, activation validation, discovery
# endpoints, AI tools) never re-hardcode it and drift. Unknown key → facility
# default (the original preset), matching prior inline behaviour.
_PRESET_OPERATIONS = {
    'smartfarmkorea': OPERATIONS,
    'smartfarmkorea_outdoor': OUTDOOR_OPERATIONS,
    'smartfarmkorea_livestock': LIVESTOCK_OPERATIONS,
}


def operations_for_preset(preset_key):
    """Map a SmartFarmKorea preset_key to its operations dict (facility
    default for unknown/blank, preserving the pre-centralisation behaviour)."""
    return _PRESET_OPERATIONS.get(preset_key, OPERATIONS)


def build_url(op_key, params, operations=None):
    """Path-segment URL for one operation. `operations` selects the dataset
    (OPERATIONS/facility by default, or OUTDOOR_OPERATIONS) — each entry
    carries its own 'base' so a facility vs outdoor op never mixes URLs even
    though several keys ('identity'/'cropping'/'env') exist in both dicts.
    Raises KeyError (unknown op_key) or ValueError (a required param is
    missing OR absent from `params` entirely — deliberately treated the same
    as empty, not a KeyError, so a caller that passes a partial dict gets one
    consistent, catchable error path instead of two)."""
    operations = operations if operations is not None else OPERATIONS
    op = operations[op_key]
    segments = [str(params.get(p, '')).strip() for p in op['params']]
    if not all(segments):
        missing = [p for p, s in zip(op['params'], segments) if not s]
        raise ValueError(f"missing required param(s) for {op_key}: {', '.join(missing)}")
    return f"{op['base']}/{op['path']}/" + "/".join(segments)


def _format_record(rec, dataset_labels=None):
    parts = []
    for k, v in rec.items():
        if k in ('statusCode', 'statusMessage') or v in (None, ''):
            continue
        parts.append(f"{_field_label(k, dataset_labels)}={v}")
    return ', '.join(parts)


def fetch_operation(op_key, params, operations=None):
    """Fetch + parse one operation. Returns (records: list[dict], error: str|None).
    Never raises — network/parse failures come back as an error string so one
    bad operation in a multi-select sync doesn't abort the others."""
    operations = operations if operations is not None else OPERATIONS
    try:
        url = build_url(op_key, params, operations=operations)
    except (KeyError, ValueError) as e:
        return None, str(e)

    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return None, f"unexpected response shape for {op_key}: {type(data).__name__}"
        status = (data[0] or {}).get('statusMessage') if data else None
        if status and status != 'NORMAL_CODE':
            return None, f"{op_key}: {status}"
        return data, None
    except requests.RequestException as e:
        return None, f"{op_key} request failed: {e}"
    except ValueError as e:  # JSON decode error
        return None, f"{op_key} returned non-JSON response: {e}"


def fetch_and_format_selected(config, operations=None):
    """Fetch every operation in config['operations'] and format them into ONE
    Korean text digest (fed to context_source_service._write_knowledge_chunks
    — the same chunk+digest pipeline a document/web_url source uses, so this
    reuses tested chunking/hashing/dedup rather than a new one-off path).
    `operations` selects OPERATIONS (facility, default), OUTDOOR_OPERATIONS,
    or LIVESTOCK_OPERATIONS — the field-label dataset (dataset_labels) is
    inferred from which dict this is, so 'itemCode' etc. read correctly per
    dataset without a shared global mistranslating one of them.

    Returns (text: str, tags: list[str], errors: list[str]). `text` is '' if
    every selected operation failed (caller treats that as a sync error);
    partial failures still produce a text block for whatever succeeded, with
    failures reported via `errors` (surfaced as sync warnings, not silently
    dropped).
    """
    operations = operations if operations is not None else OPERATIONS
    dataset_labels = _LIVESTOCK_FIELD_LABELS if operations is LIVESTOCK_OPERATIONS else None
    selected = config.get('operations') or []
    text_blocks = []
    tags = set()
    errors = []

    for op_key in selected:
        op = operations.get(op_key)
        if not op:
            errors.append(f"unknown operation: {op_key}")
            continue

        params = {p: config.get(p, '') for p in op['params']}
        params['serviceKey'] = config.get('api_key', '')
        records, err = fetch_operation(op_key, params, operations=operations)
        if err:
            errors.append(err)
            continue
        if not records:
            errors.append(f"{op_key}: no data returned")
            continue

        tags.add(op['category'])
        tags.add(op_key)
        capped = records[:_MAX_RECORDS_PER_OP]
        lines = [f"### {op['label_ko']} ({len(records)}건 중 {len(capped)}건 표시)"]
        for rec in capped:
            formatted = _format_record(rec, dataset_labels)
            if formatted:
                lines.append(f"- {formatted}")
        if len(records) > _MAX_RECORDS_PER_OP:
            lines.append(f"... 외 {len(records) - _MAX_RECORDS_PER_OP}건 생략")
        text_blocks.append('\n'.join(lines))

    text = '\n\n'.join(text_blocks)
    return text, sorted(tags), errors


# ---------------------------------------------------------------------------
# Discovery primitive (Phase 1) — the shared core behind BOTH the cascading
# settings-modal pickers and (Phase 2) the AI-driven setup tools. Turns the
# API's relational drill-down (identity → cropping → codes) into
# human-readable option lists so nobody — human or AI — has to eyeball a
# 2,300-row dump and hand-copy a userId/croppingSerlNo. See
# docs/design/ai-library-redesign.md and the module docstring's discovery
# note. Only meaningful for facility/outdoor (they have identity/cropping);
# livestock has no discovery chain (see EXT-KR-06 note).
# ---------------------------------------------------------------------------

def _s(val):
    """Coerce an API field to a stripped string. The SmartFarmKorea JSON
    returns some id fields as NUMBERS (e.g. croppingSerlNo=79, not "79"), so a
    bare `.strip()` on the raw value AttributeErrors — confirmed live."""
    return '' if val is None else str(val).strip()


def resolve_farms(service_key, operations=None):
    """Call the dataset's `identity` op and return farm options for a picker:
    [{value, label, userId, facilityId, itemCode, crop}]. `value` is the userId
    (the join key the other operations need); `label` is human-readable
    (region + CROP NAME + userId — crop name, not the raw itemCode, so the
    operator/AI can tell a 딸기 farm from a 토마토 one). `crop` is the resolved
    crop name (or raw code if unmapped). Returns (farms, error) — never raises
    (mirrors fetch_operation's contract)."""
    operations = operations if operations is not None else OPERATIONS
    if 'identity' not in operations:
        return None, 'this dataset has no identity/discovery operation'
    records, err = fetch_operation('identity', {'serviceKey': service_key}, operations=operations)
    if err:
        return None, err
    farms = []
    for r in (records or []):
        uid = _s(r.get('userId'))
        if not uid:
            continue
        region = _s(r.get('addressName'))
        item = _s(r.get('itemCode'))
        crop = crop_name(item)  # crop name if known, else the raw code
        label = region or uid
        if crop:
            label = f"{label} · {crop}"
        label = f"{label} ({uid})"
        farms.append({
            'value': uid, 'label': label, 'userId': uid,
            'facilityId': _s(r.get('facilityId')), 'itemCode': item, 'crop': crop,
        })
    return farms, None


def resolve_seasons(service_key, user_id, operations=None):
    """Call the dataset's `cropping` op for one farm and return season options
    for a picker: [{value, label, croppingSerlNo, itemCode}]. `value` is the
    croppingSerlNo (what growth ops need); `label` is the human-readable
    croppingSeasonName. Returns (seasons, error) — never raises."""
    operations = operations if operations is not None else OPERATIONS
    if 'cropping' not in operations:
        return None, 'this dataset has no cropping operation'
    if not _s(user_id):
        return None, 'userId is required to look up seasons'
    records, err = fetch_operation(
        'cropping', {'serviceKey': service_key, 'userId': user_id}, operations=operations)
    if err:
        return None, err
    seasons = []
    for r in (records or []):
        serl = _s(r.get('croppingSerlNo'))
        if not serl:
            continue
        name = _s(r.get('croppingSeasonName'))
        item = _s(r.get('itemCode'))
        seasons.append({
            'value': serl, 'label': name or serl, 'croppingSerlNo': serl,
            'itemCode': item, 'crop': crop_name(item),
        })
    return seasons, None
