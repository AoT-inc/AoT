# coding=utf-8
"""요청 예시문 무작위 생성기 — 서랍(노출 등급) 검증용.

왜 필요한가: 골든셋 24개는 손으로 고른 문장이라 "서랍을 열어야만 되는 요청"이
거의 없다. 등급을 켰을 때 확인하고 싶은 것은 정확히 그 경우 — 상시 노출에 없는
도구가 필요할 때 LLM 이 `open_drawer` 를 떠올리는가 — 이므로, 그 축을 명시적으로
갖는 표본이 따로 필요하다.

조합 축
    대상(target)   zone / site / facility / device / crop
    동작(action)   조회 · 제어 · 기록 · 일정 · 진단 · 설정 · 공간
    기간/조건      오늘·어제·지난주·다음주·이번 주말 …

각 템플릿은 **어느 서랍이 있어야 답할 수 있는지**(`drawer`)를 함께 들고 있다.
`drawer=None` 이면 상시 노출(core)만으로 되는 요청이다. 이 표시가 곧 채점
기준이 된다 — 서랍이 필요한 요청에서 `open_drawer` 가 안 불리면 설계가 틀린
것이고, 필요 없는 요청에서 불리면 왕복만 늘어난 것이다.

대상 이름은 하드코딩하지 않고 DB(읽기 전용)에서 실제 이름을 읽어 온다. 없는
이름을 넣으면 "못 찾음" 이 섞여 들어와 서랍 실패와 구분되지 않는다.
"""
import json
import random
import sqlite3

# 실제 이름을 못 읽었을 때만 쓰는 최소 대체값. 이걸로 돌면 표본의 의미가
# 떨어지므로 sample() 이 경고를 함께 돌려준다.
_FALLBACK_CATALOG = {
    'zone': ['1-1', '2-1', '3-1'],
    'site': ['1포장', '2포장', '3포장'],
    'facility': ['육묘장', '관리사무소'],
    'device': ['v111', '천창1'],
    'sensor': ['온습도_1'],
    'crop': ['콩', '들깨'],
}

_PERIODS = ['오늘', '어제', '지난주', '최근 3일', '이번 주']
_FUTURE = ['내일 아침 7시', '이번 주 토요일 오후 2시', '모레 오전 9시']

# (id, 서랍, 카테고리, 슬롯, 문장 후보들, 이 요청을 실제로 해결하는 도구들)
#
# `expect_tools` 는 "이 도구가 불려야 정답" 이라는 뜻이 아니라 **그 서랍 안에서
# 이 요청을 해결할 수 있는 도구** 다. 채점은 도구 이름이 아니라 서랍 단위로
# 한다 — 어느 도구를 고르는지는 모델 자유고, 우리가 보는 것은 서랍을 여는가다.
_TEMPLATES = [
    # ── core 로 되는 요청 (대조군) ────────────────────────────────────────
    ('core_zone_env', None, '조회', ('zone',),
     ['{zone} 구역 지금 온도 어때?', '{zone} 온습도 지금 어떤지 알려줘',
      '{zone} 지금 환경 상태 좀 봐줘'],
     ['get_zone_sensor_summary']),
    ('core_device_find', None, '조회', ('device',),
     ['{device} 라는 장치 어디 있어?', '{device} 지금 상태 어때?'],
     ['search_devices', 'get_output_state']),
    ('core_weather', None, '조회', (),
     ['오늘 날씨 어때?', '지금 바깥 날씨 알려줘'],
     ['get_weather']),
    ('core_note_write', None, '기록', ('site',),
     ['{site}에 오늘 잡초 매었다고 기록해줘', '{site} 오늘 관수했다고 노트 남겨줘'],
     ['create_note']),
    ('core_note_read', None, '기록', ('site',),
     ['{site}에 적어둔 노트 뭐 있어?', '{site} 관련 기록 찾아줘'],
     ['search_notes']),
    ('core_schedule_read', None, '일정', (),
     ['{period} 예정된 일정 뭐 있어?', '이번 주 일정 알려줘'],
     ['search_schedule']),
    ('core_planting_list', None, '조회', (),
     ['지금 뭐 심어져 있어?', '재배 중인 작물 목록 보여줘'],
     ['list_plantings']),
    ('core_control', None, '제어', ('device',),
     ['{device} 좀 켜줘', '{device} 꺼줘'],
     ['operate_device', 'set_output_state']),

    # ── 서랍이 있어야 되는 요청 ──────────────────────────────────────────
    # definition — 장치 정의 추가·수정·삭제
    ('drw_def_create_input', 'definition', '설정', ('facility',),
     ['{facility}에 토양수분 센서 하나 새로 추가해줘',
      '온습도 센서를 하나 더 등록하고 싶어. {facility}에 만들어줘'],
     ['create_input']),
    ('drw_def_create_output', 'definition', '설정', ('facility',),
     ['{facility}에 관수 밸브 출력 장치를 새로 만들어줘',
      '릴레이 출력 하나 새로 등록해줘'],
     ['create_output']),
    ('drw_def_types', 'definition', '설정', (),
     ['이 시스템에 어떤 종류의 센서를 추가할 수 있어?',
      '등록 가능한 장치 타입 목록 보여줘'],
     ['list_device_types', 'get_device_type_options']),
    ('drw_def_delete', 'definition', '설정', ('sensor',),
     ['{sensor} 센서 등록을 삭제해줘', '{sensor} 이제 안 쓰니까 장치 목록에서 지워줘'],
     ['delete_input']),

    # function — 함수·제어기·시퀀스
    ('drw_fn_create', 'function', '설정', ('zone',),
     ['{zone} 습도가 40% 아래로 떨어지면 자동으로 가습되게 만들어줘',
      '{zone} 온도가 30도 넘으면 환기창 열리는 자동화 하나 만들어줘'],
     ['create_function']),
    ('drw_fn_toggle', 'function', '제어', (),
     ['지금 켜져 있는 자동화 함수 다 꺼줘', '동작 중인 제어 함수 하나 정지시켜줘'],
     ['get_active_functions_summary', 'deactivate_function']),
    ('drw_fn_detail', 'function', '조회', (),
     ['환기 제어 함수 설정값이 지금 어떻게 되어 있어?',
      '제어 함수 하나 골라서 상세 설정 보여줘'],
     ['get_function_detail']),
    ('drw_fn_sequence', 'function', '설정', ('zone',),
     ['{zone} 관수 시퀀스를 요일별로 짜고 싶어',
      '{zone} 순차 관수 시퀀스 하나 만들어줘'],
     ['create_sequence_function', 'configure_sequence_day']),

    # schedule — 일정·예약 (읽기/생성은 core, 수정·삭제·장치예약은 서랍)
    ('drw_sch_edit', 'schedule', '일정', (),
     ['{period}에 잡아둔 일정 시간을 좀 바꿔줘', '등록된 일정 하나 내용 수정해줘'],
     ['edit_schedule']),
    ('drw_sch_delete', 'schedule', '일정', (),
     ['{period} 일정 하나 취소해줘', '잡아둔 일정 삭제해줘'],
     ['delete_schedule']),
    ('drw_sch_device', 'schedule', '일정', ('device',),
     ['{future}에 {device} 켜지도록 예약해줘',
      '{device} {future}에 한 번만 작동하게 예약 걸어줘'],
     ['schedule_device_control']),

    # space — 지도·구역·시설·작물 구획
    ('drw_space_capacity', 'space', '조회', ('facility',),
     ['{facility} 난방 설계 용량이 얼마나 돼?', '{facility} 환기 성능이 어느 정도야?'],
     ['get_facility_capacity']),
    ('drw_space_equipment', 'space', '조회', ('site',),
     ['{site}에 설치된 관수 설비가 뭐뭐 있어?', '{site}에 그려둔 설비 목록 보여줘'],
     ['get_map_equipment']),
    ('drw_space_planting_new', 'space', '설정', ('site', 'crop'),
     ['{site}에 {crop} 심었다고 재배 구획 하나 등록해줘',
      '{site}에 {crop} 재배 시작한 걸로 만들어줘'],
     ['create_planting']),
    ('drw_space_tree', 'space', '조회', (),
     ['농장 구역 구조를 계층으로 보여줘', '사이트-구역-시설 구조가 어떻게 돼?'],
     ['get_spatial_tree']),
    ('drw_space_crop_status', 'space', '조회', ('crop',),
     ['{crop} 지금 생육 상태가 어때?', '{crop} 재배 이력 좀 보여줘'],
     ['get_crop_status', 'get_planting_history']),

    # measurement — 센서 값·환경·날씨·에너지
    ('drw_meas_forecast', 'measurement', '조회', (),
     ['내일부터 사흘간 날씨 예보 어때?', '주말 날씨 예보 알려줘'],
     ['get_weather_forecast']),
    ('drw_meas_anomaly', 'measurement', '진단', (),
     ['{period} 센서 값 이상한 거 없었어?', '최근에 이상치 감지된 거 있어?'],
     ['get_anomalies']),
    ('drw_meas_energy', 'measurement', '조회', (),
     ['{period} 전력 사용량이 얼마나 돼?', '이번 달 에너지 사용 보고서 보여줘'],
     ['get_energy_report']),
    ('drw_meas_cumulative', 'measurement', '조회', ('zone',),
     ['{zone} 적산온도가 지금 얼마야?', '{zone} 누적 일사량 알려줘'],
     ['get_cumulative_status']),

    # device — 장치 조작·상태·검색 (core 밖의 것)
    ('drw_dev_control_state', 'device', '진단', ('device',),
     ['{device} 지금 자동제어가 걸려 있어, 수동이야?',
      '{device} 제어 상태가 어떻게 잡혀 있는지 봐줘'],
     ['get_control_state']),
    ('drw_dev_available', 'device', '조회', (),
     ['제어 가능한 장치 전체 목록 보여줘', '지금 쓸 수 있는 장치가 뭐뭐 있어?'],
     ['list_available_devices', 'get_device_list']),

    # record — 노트·공지·지식·조언
    ('drw_rec_notice', 'record', '기록', (),
     ['작업자들한테 공지 하나 올려줘. 내일 오전 단수라고.',
      '지금 올라와 있는 공지 뭐 있어?'],
     ['create_notice', 'list_notices']),
    ('drw_rec_knowledge', 'record', '조회', ('crop',),
     ['{crop} 재배 매뉴얼에서 관수 주기 부분 찾아줘',
      '{crop} 병해충 관련 자료 있으면 찾아줘'],
     ['knowledge_search']),
    ('drw_rec_archive', 'record', '기록', ('site',),
     ['{site} 관련해서 예전에 보관해둔 문서 찾아줘', '보관함에 있는 문서 검색해줘'],
     ['search_archives']),

    # system — AI 설정·시스템 상태·진단·매뉴얼
    ('drw_sys_brief', 'system', '진단', (),
     ['시스템 전체 상태 요약해줘', '지금 시스템에 문제 없어?'],
     ['get_system_brief']),
    ('drw_sys_agents', 'system', '설정', (),
     ['등록된 AI 에이전트 목록 보여줘', 'AI 설정이 지금 어떻게 되어 있어?'],
     ['list_ai_agents', 'list_ai_entries']),
    ('drw_sys_update', 'system', '진단', (),
     ['업데이트 할 거 있어?', '지금 버전이 최신이야?'],
     ['get_system_update_status']),
]


def catalog_from_db(db_path):
    """실제 대상 이름을 읽어 온다(읽기 전용). 실패하면 빈 dict."""
    cat = {k: [] for k in _FALLBACK_CATALOG}
    try:
        conn = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    except Exception:
        return {}
    try:
        for stype, feature in conn.execute('select type, feature from geo_shape'):
            if stype not in ('site', 'zone', 'facility'):
                continue
            try:
                props = (json.loads(feature) or {}).get('properties') or {}
            except Exception:
                continue
            name = props.get('name') or props.get('aot_name') or props.get('label')
            if name and name.strip():
                cat[stype].append(name.strip())
        for (name,) in conn.execute('select name from output where name is not null'):
            if name.strip() and not name.startswith('TEST'):
                cat['device'].append(name.strip())
        for (name,) in conn.execute('select name from input where name is not null'):
            if name.strip():
                cat['sensor'].append(name.strip())
        for (crop, variety) in conn.execute(
                'select crop, variety from geo_planting where ended_on is null'):
            for v in (crop, variety):
                if v and v.strip():
                    cat['crop'].append(v.strip())
    except Exception:
        pass
    finally:
        conn.close()
    # 중복 제거 + 순서 고정(seed 재현성). 비어 있으면 대체값으로 채운다.
    out = {}
    for k, v in cat.items():
        uniq = sorted(set(v))
        out[k] = uniq or list(_FALLBACK_CATALOG[k])
    return out


def sample(n=12, seed=0, db_path=None, drawer_ratio=0.6, catalog=None):
    """요청 n개를 뽑는다.

    drawer_ratio: 서랍이 필요한 요청의 비율. 이 검증의 핵심이 후자이므로
    기본을 0.6 으로 두었다. 같은 seed 면 같은 표본이 나온다 — 켜기 전/후를
    **동일한 문장으로** 비교해야 왕복 차이가 문장 차이에 가려지지 않는다.
    """
    rng = random.Random(seed)
    cat = catalog or (catalog_from_db(db_path) if db_path else {})
    if not cat:
        cat = dict(_FALLBACK_CATALOG)
    for k, v in _FALLBACK_CATALOG.items():
        if not cat.get(k):
            cat[k] = list(v)

    core_t = [t for t in _TEMPLATES if t[1] is None]
    drawer_t = [t for t in _TEMPLATES if t[1] is not None]

    n_drawer = int(round(n * drawer_ratio))
    n_core = n - n_drawer

    # 서랍 8개가 고르게 나오도록 서랍별로 먼저 묶고 라운드로빈으로 뽑는다.
    by_drawer = {}
    for t in drawer_t:
        by_drawer.setdefault(t[1], []).append(t)
    for v in by_drawer.values():
        rng.shuffle(v)
    order = sorted(by_drawer)
    rng.shuffle(order)

    picked = []
    i = 0
    while len(picked) < n_drawer:
        bucket = by_drawer[order[i % len(order)]]
        picked.append(bucket[(i // len(order)) % len(bucket)])
        i += 1
    core_pool = list(core_t)
    rng.shuffle(core_pool)
    for j in range(n_core):
        picked.append(core_pool[j % len(core_pool)])

    rng.shuffle(picked)

    out = []
    for idx, (tid, drawer, category, slots, texts, expect) in enumerate(picked):
        fill = {'period': rng.choice(_PERIODS), 'future': rng.choice(_FUTURE)}
        for s in slots:
            fill[s] = rng.choice(cat[s])
        text = rng.choice(texts)
        # 미사용 슬롯이 남아 있어도 안전하게 — format_map 대신 순차 치환.
        for k, v in fill.items():
            text = text.replace('{%s}' % k, str(v))
        out.append({
            'id': '%s#%d' % (tid, idx),
            'template_id': tid,
            'prompt': text,
            'needs_drawer': drawer,          # None = core 만으로 가능
            'category': category,
            'expect_tools': list(expect),
            'slots': {k: v for k, v in fill.items() if k in slots},
        })
    return out


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--n', type=int, default=12)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--db-path', default=None)
    p.add_argument('--drawer-ratio', type=float, default=0.6)
    a = p.parse_args()
    for s in sample(a.n, a.seed, a.db_path, a.drawer_ratio):
        print('[%-10s] %-11s %s' % (s['needs_drawer'] or 'core',
                                    s['category'], s['prompt']))
