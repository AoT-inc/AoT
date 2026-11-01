#!/usr/bin/env python3
# coding=utf-8
"""김제 육묘장3 스냅숏에 **가상 터널팬**(흡기 1 + 배기 1)을 붙인 사본을 만든다.

`--roles circulation_fan` 이면 대신 **가상 순환팬 1대**(집 가운데, 기본 10200 m³/h = 바닥 340 m² × 30)를 붙인다
(밤 이슬 순환팬 시험용 변형 `circfan`, 2026-10-12). `--roles` 는 쉼표로 여럿을 줄 수 있다.

실험용이다 — 현장에는 팬이 없다(측창 2 + 분무 1). 원본 스냅숏은 건드리지 않고
**새 파일**을 만든다. 운영·개발서버 DB 에는 절대 쓰지 않는다(아래 가드).

바인딩은 현행 시설 디자이너가 저장하는 두 갈래를 **둘 다** 쓴다:

  1. `geo_facility.actuators` 목록형(ActuatorUI) 항목
       {kind: 'intake_fan'|'exhaust_fan', device_uuid, specs: {airflow_cmh}}
     → `facility_integration` 이 `_ACTUATOR_UI_KIND_TO_KIND` 로 kind 를 정하고
       `specs.airflow_cmh` 를 `rated_m3h` 로 넘긴다. **풍량이 제어기에 닿는 길은
       이것뿐이다** — 피팅 경로는 kind 만 정하고 풍량을 옮기지 않는다(팬 피팅만
       있으면 `_KIND_DEFAULT_RATED_M3H` 3000 m³/h 로 떨어진다).
  2. `geo_facility.fittings` 의 'fan' 피팅(fan_role, actuator_id, 위치·법선)
     → 도면 위치(박공 양끝)와 시설 소속(bay)을 준다.

Output 은 현장 분무기와 같은 `virtual_on_off_single`(릴레이 on/off → 코디네이터의
TimeProportionalAdapter 가 사이클 내 켬 시간으로 보낸다). `--output-type python_pwm`
이면 PwmAdapter(가동률 %) 경로를 시험할 수 있다.

UUID 는 이름에서 결정적으로 만든다(uuid5) — 같은 입력이면 같은 사본이 나와 A/B 추적이
서로 맞는다.

사용:
  python3 make_gimje_fans_db.py --roles circulation_fan \
      --src .../aot.db.snap --dst .../aot_circfan.db.snap        # 순환팬만
  python3 make_gimje_fans_db.py \
      --src /Users/gwansuk/Github/AoT_dev/env-replay/gimje/aot_local/databases/aot.db.snap \
      --dst /Users/gwansuk/Github/AoT_dev/env-replay/gimje/aot_local/databases/aot_fans.db.snap
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import uuid

GIMJE_FACILITY = 'a3d725da-665f-496f-9146-d06135178064'
NS = uuid.UUID('6f1d2c3a-5b4e-4f00-9a7c-0e5c1a2b3c4d')


def _guard(path: str) -> None:
    rp = os.path.realpath(path)
    base = os.path.basename(rp)
    # 살아 있는 DB 이름(aot.db)·개발서버 마운트 경로에는 쓰지 않는다.
    if base == 'aot.db' or os.sep + 'Github' + os.sep + 'AoT_ai' + os.sep + 'aot_local' in rp:
        sys.exit(f'거부: 살아 있는 DB 로 보이는 경로입니다 — {rp}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--src', required=True)
    ap.add_argument('--dst', required=True)
    ap.add_argument('--facility', default=GIMJE_FACILITY)
    ap.add_argument('--intake-m3h', type=float, default=48000.0)
    ap.add_argument('--exhaust-m3h', type=float, default=48000.0)
    ap.add_argument('--circulation-m3h', type=float, default=10200.0)
    ap.add_argument('--roles', default='intake_fan,exhaust_fan',
                    help='붙일 팬 종류(쉼표): intake_fan · exhaust_fan · circulation_fan')
    ap.add_argument('--output-type', default='virtual_on_off_single')
    ap.add_argument('--force', action='store_true', help='dst 가 있으면 덮어쓴다')
    a = ap.parse_args()

    if os.path.realpath(a.src) == os.path.realpath(a.dst):
        sys.exit('거부: src 와 dst 가 같습니다')
    _guard(a.dst)
    if os.path.exists(a.dst) and not a.force:
        sys.exit(f'이미 있습니다(덮어쓰려면 --force): {a.dst}')
    shutil.copyfile(a.src, a.dst)

    db = sqlite3.connect(a.dst)
    db.row_factory = sqlite3.Row
    try:
        fac = db.execute('select geometry_3d, fittings, actuators from geo_facility '
                         'where unique_id = ?', (a.facility,)).fetchone()
        if fac is None:
            sys.exit(f'시설이 없습니다: {a.facility}')
        geom = json.loads(fac['geometry_3d'] or '{}') or {}
        fittings = json.loads(fac['fittings'] or '[]') or []
        acts = json.loads(fac['actuators'] or '[]') or []
        if not isinstance(acts, list):
            sys.exit('actuators 가 목록형이 아닙니다 — 이 스크립트는 목록형 시설만 다룬다')
        span = float(geom.get('span_width_m') or 7.0)
        length = float(geom.get('length_m') or 48.5)

        tmpl = db.execute('select * from output where output_type = ? limit 1',
                          (a.output_type,)).fetchone()
        if tmpl is None:
            sys.exit(f'틀로 쓸 Output 이 없습니다(output_type={a.output_type})')
        tmpl_ch = db.execute('select custom_options from output_channel where output_id = ? '
                             'and channel = 0', (tmpl['unique_id'],)).fetchone()
        cols = [c for c in tmpl.keys() if c != 'id']
        made = []
        wanted = [r.strip() for r in a.roles.split(',') if r.strip()]
        catalog = {
            'intake_fan': (a.intake_m3h, 0.0, [0, 0, -1], '흡기'),
            'exhaust_fan': (a.exhaust_m3h, length, [0, 0, 1], '배기'),
            'circulation_fan': (a.circulation_m3h, length / 2.0, [0, -1, 0], '순환'),
        }
        unknown = [r for r in wanted if r not in catalog]
        if unknown or not wanted:
            sys.exit(f'알 수 없는 --roles: {unknown or a.roles}')
        for role, (m3h, z, normal, label) in ((r, catalog[r]) for r in wanted):
            oid = str(uuid.uuid5(NS, f'gimje-{a.facility}-{role}'))
            if db.execute('select 1 from output where unique_id = ?', (oid,)).fetchone():
                sys.exit(f'이미 가상 팬이 있습니다: {oid}')
            row = {c: tmpl[c] for c in cols}
            row.update(unique_id=oid, name=f'시뮬-가상 {label}팬',
                       position_y=(tmpl['position_y'] or 0) + 50 + len(made))
            db.execute(f'insert into output ({",".join(cols)}) values '
                       f'({",".join("?" * len(cols))})', [row[c] for c in cols])
            db.execute('insert into output_channel (unique_id, output_id, channel, name, '
                       'custom_options) values (?, ?, 0, ?, ?)',
                       (str(uuid.uuid5(NS, oid + '-ch0')), oid, '',
                        (tmpl_ch['custom_options'] if tmpl_ch else '{}')))
            fid = 'Fsim_' + role
            fittings.append({
                'actuator_id': oid, 'channel_measurements': [], 'fan_role': role,
                'id': fid, 'input_id': None, 'kind': 'fan', 'link_group': None,
                'name': f'가상 {label}팬', 'position': {'x': span / 2.0, 'y': 1.5, 'z': z},
                'replica_info': None, 'rotation_deg': 0,
                'size': {'d': 0.4, 'h': 1.4, 'w': 1.4}, 'surface_normal': normal,
                'airflow_cmh': m3h, '_sim_virtual': True})
            acts.append({
                'id': 'Asim_' + role, 'kind': role, 'device_uuid': oid,
                'mount': {'wall': ('z_neg' if z == 0 else 'z_pos')
                          if role != 'circulation_fan' else 'ceiling'},
                'specs': {'airflow_cmh': m3h, 'power_w': round(m3h / 30000.0 * 1000.0)},
                '_sim_virtual': True})
            made.append((role, oid, m3h))
        db.execute('update geo_facility set fittings = ?, actuators = ? where unique_id = ?',
                   (json.dumps(fittings, ensure_ascii=False),
                    json.dumps(acts, ensure_ascii=False), a.facility))
        db.commit()
    finally:
        db.close()
    for role, oid, m3h in made:
        print(f'{role:12s} {oid}  {m3h:.0f} m³/h')
    print(f'→ {a.dst}')


if __name__ == '__main__':
    main()
