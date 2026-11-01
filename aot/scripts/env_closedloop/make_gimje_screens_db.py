#!/usr/bin/env python3
# coding=utf-8
"""김제 육묘장3 스냅숏(또는 그 팬 사본)에 **가상 차광막·보온커튼**을 붙인 사본을 만든다.

실험용이다 — 현장에는 스크린이 없다. 원본 스냅숏은 건드리지 않고 **새 파일**을 만든다.
운영·개발서버 DB 에는 절대 쓰지 않는다(아래 가드). `make_gimje_fans_db.py` 와 같은 방식이다.

붙이는 것(`geo_facility.actuators` 목록형 항목 + Output 두 개):

  shade_curtain_motor    차광막   → 코디네이터 kind 'shade',   시설 모델 'shade'
  thermal_curtain_motor  보온커튼 → 코디네이터 kind 'curtain', 시설 모델 'curtain'

Output 은 `actuator_paired`(PairedAdapter — 개도 % 를 그대로 보낸다)이고, 채널 옵션에
주행 시간(`travel_time_open/close_sec`, 기본 240 s)을 적는다 — 코디네이터는 이것으로 **부분
개도가 되는 스크린**(`screen_positional`)인지 가른다. `--binary` 면 주행 시간을 적지 않는다
(같은 모터지만 코디네이터가 0/100 으로만 쓴다 — 틈·램프 없음). 시설 모델의 주행은 둘 다 240 s 다.

시설 외피(`envelope.curtain`)에 차광막(`shade.enabled`, 투과율 `--shade-tau`)과 보온커튼
(`thermal_ceiling.enabled`)을 켠다 — 코디네이터의 실내 광량 추정·DLI 예상이 그 값을 읽는다.
시설 모델의 차광 투과율은 `PlantParams.shade_tau`(0.45)다 — 기본값을 그것과 맞췄다.

실외 일사 채널도 붙인다(`--no-solar` 로 끔): 김제 실외 장치(기상청)에는 일사가 없어 코디네이터가
해를 모른다 — 그러면 차광막 효과 모델(일사 비례)·광 상태·극한 고온 보호의 차광이 모두 쉰다. 그 장치에
`radiation`(W/m²) 측정 하나를 더하고 시설 센서 피팅의 채널 목록에 `light` 로 올린다. 하네스는 그
채널에 시나리오 외기의 일사를 낸다. (원본 `orig` 와 견줄 때 이 차이 — 해를 안다 — 도 함께 들어간다.)

UUID 는 이름에서 결정적으로 만든다(uuid5) — 같은 입력이면 같은 사본이 나온다. 가상 팬
사본에 붙여도(`--src aot_fans.db.snap`) 이름이 겹치지 않는다.

사용:
  G=/Users/gwansuk/Github/AoT_dev/env-replay/gimje/aot_local/databases
  python3 make_gimje_screens_db.py --src $G/aot.db.snap --dst <site>/aot_local/databases/aot_screens.db.snap
  python3 make_gimje_screens_db.py --src $G/aot.db.snap --dst .../aot_screens_binary.db.snap --binary
  python3 make_gimje_screens_db.py --src $G/aot_fans.db.snap --dst .../aot_fans_screens.db.snap
  python3 make_gimje_screens_db.py --src $G/aot.db.snap --dst .../aot_screens_heated.db.snap --heater-kw 40
"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
import uuid

GIMJE_FACILITY = 'a3d725da-665f-496f-9146-d06135178064'
NS = uuid.UUID('6f1d2c3a-5b4e-4f00-9a7c-0e5c1a2b3c4e')

_SCREENS = (
    # (목록 kind, 채널 actuator_kind, 이름)
    ('shade_curtain_motor', 'shade_curtain', '차광막'),
    ('thermal_curtain_motor', 'thermal_curtain', '보온커튼'),
)


def _guard(path: str) -> None:
    rp = os.path.realpath(path)
    base = os.path.basename(rp)
    # 살아 있는 DB 이름(aot.db)·개발서버 마운트 경로·원본 스냅숏 이름에는 쓰지 않는다.
    if (base in ('aot.db', 'aot.db.snap')
            or os.sep + 'Github' + os.sep + 'AoT_ai' + os.sep + 'aot_local' in rp):
        sys.exit(f'거부: 살아 있는 DB 또는 원본 스냅숏으로 보이는 경로입니다 — {rp}')


def _add_solar_channel(db, fittings, facility) -> str:
    """실외 센서 피팅의 장치에 `radiation`(W/m²) 측정을 더하고 피팅 채널 목록에 올린다 → 측정 id."""
    out_fit = None
    for f in fittings:
        if f.get('kind') != 'sensor' or not f.get('input_id'):
            continue
        n = db.execute("select count(*) from device_measurements where device_id = ? and "
                       "measurement in ('direction', 'speed', 'precipitation')",
                       (f['input_id'],)).fetchone()[0]
        if n:
            out_fit = f
            break
    if out_fit is None:
        sys.exit('실외 센서 피팅(풍향·풍속·강수 채널을 가진 장치)이 없습니다')
    dev = out_fit['input_id']
    tmpl = db.execute('select * from device_measurements where device_id = ? '
                      'order by channel desc limit 1', (dev,)).fetchone()
    cols = [c for c in tmpl.keys() if c != 'id']
    mid = str(uuid.uuid5(NS, f'gimje-{facility}-solar'))
    row = {c: tmpl[c] for c in cols}
    row.update(unique_id=mid, name='시뮬-일사', measurement='radiation', unit='W_m2',
               channel=int(tmpl['channel'] or 0) + 1, rescaled_measurement=None,
               rescaled_unit=None, conversion_id=None)
    if 'measurement_type' in row:
        row['measurement_type'] = None
    db.execute(f'insert into device_measurements ({",".join(cols)}) values '
               f'({",".join("?" * len(cols))})', [row[c] for c in cols])
    out_fit.setdefault('channel_measurements', []).append(
        {'measurement_id': mid, 'measurement_type': 'light'})
    return mid


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--src', required=True)
    ap.add_argument('--dst', required=True)
    ap.add_argument('--facility', default=GIMJE_FACILITY)
    ap.add_argument('--travel', type=float, default=240.0, help='편도 주행 시간(s)')
    ap.add_argument('--shade-tau', type=float, default=0.45, help='닫힌 차광막 투과율')
    ap.add_argument('--binary', action='store_true',
                    help='주행 시간을 적지 않는다 — 코디네이터가 0/100 으로만 쓴다')
    ap.add_argument('--only', choices=('shade', 'curtain'),
                    help='하나만 붙인다(기본: 둘 다)')
    ap.add_argument('--no-solar', action='store_true', help='실외 일사 채널을 붙이지 않는다')
    ap.add_argument('--heater-kw', type=float, default=0.0,
                    help='가상 난방기(on/off, kW)도 붙인다 — 보온커튼 틈·아침 램프의 열 손실 시험용')
    ap.add_argument('--force', action='store_true', help='dst 가 있으면 덮어쓴다')
    a = ap.parse_args()

    if os.path.realpath(a.src) == os.path.realpath(a.dst):
        sys.exit('거부: src 와 dst 가 같습니다')
    _guard(a.dst)
    if os.path.exists(a.dst) and not a.force:
        sys.exit(f'이미 있습니다(덮어쓰려면 --force): {a.dst}')
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    shutil.copyfile(a.src, a.dst)

    db = sqlite3.connect(a.dst)
    db.row_factory = sqlite3.Row
    made = []
    try:
        fac = db.execute('select envelope, actuators, fittings from geo_facility '
                         'where unique_id = ?', (a.facility,)).fetchone()
        if fac is None:
            sys.exit(f'시설이 없습니다: {a.facility}')
        env = json.loads(fac['envelope'] or '{}') or {}
        acts = json.loads(fac['actuators'] or '[]') or []
        if not isinstance(acts, list):
            sys.exit('actuators 가 목록형이 아닙니다 — 이 스크립트는 목록형 시설만 다룬다')

        tmpl = db.execute("select * from output where output_type = 'actuator_paired' "
                          "limit 1").fetchone()
        if tmpl is None:
            sys.exit("틀로 쓸 Output 이 없습니다(output_type='actuator_paired')")
        cols = [c for c in tmpl.keys() if c != 'id']
        for ui_kind, ch_kind, label in _SCREENS:
            if a.only and not ui_kind.startswith(
                    {'shade': 'shade', 'curtain': 'thermal'}[a.only]):
                continue
            oid = str(uuid.uuid5(NS, f'gimje-{a.facility}-{ui_kind}'))
            if db.execute('select 1 from output where unique_id = ?', (oid,)).fetchone():
                sys.exit(f'이미 가상 스크린이 있습니다: {oid}')
            row = {c: tmpl[c] for c in cols}
            row.update(unique_id=oid, name=f'시뮬-가상 {label}',
                       position_y=(tmpl['position_y'] or 0) + 60 + len(made))
            db.execute(f'insert into output ({",".join(cols)}) values '
                       f'({",".join("?" * len(cols))})', [row[c] for c in cols])
            ch = {'actuator_kind': ch_kind, 'effective_start_pct': 0.0,
                  'effective_end_pct': 100.0, 'move_step_pct': 5.0,
                  'last_position_pct': 100.0, 'last_target_pct': 100.0,
                  'invert_direction': False}
            if not a.binary:
                ch['travel_time_open_sec'] = a.travel
                ch['travel_time_close_sec'] = a.travel
            db.execute('insert into output_channel (unique_id, output_id, channel, name, '
                       'custom_options) values (?, ?, 0, ?, ?)',
                       (str(uuid.uuid5(NS, oid + '-ch0')), oid, '', json.dumps(ch)))
            acts.append({'id': 'Asim_' + ui_kind, 'kind': ui_kind, 'device_uuid': oid,
                         'mount': {'layer': 'ceiling'}, 'specs': {}, '_sim_virtual': True})
            made.append((ui_kind, oid))

        cur = env.setdefault('curtain', {})
        if any(k == 'shade_curtain_motor' for k, _ in made):
            cur['shade'] = {'enabled': True, 'transmittance': a.shade_tau,
                            '_sim_virtual': True}
        if any(k == 'thermal_curtain_motor' for k, _ in made):
            tc = cur.setdefault('thermal_ceiling', {})
            tc.update({'enabled': True, 'layers': tc.get('layers') or 1,
                       '_sim_virtual': True})
        if a.heater_kw > 0:
            htm = db.execute("select * from output where output_type = 'virtual_on_off_single' "
                             "limit 1").fetchone()
            if htm is None:
                sys.exit("틀로 쓸 Output 이 없습니다(output_type='virtual_on_off_single')")
            hcols = [c for c in htm.keys() if c != 'id']
            hid = str(uuid.uuid5(NS, f'gimje-{a.facility}-heater'))
            hrow = {c: htm[c] for c in hcols}
            hrow.update(unique_id=hid, name='시뮬-가상 난방기',
                        position_y=(htm['position_y'] or 0) + 70)
            db.execute(f'insert into output ({",".join(hcols)}) values '
                       f'({",".join("?" * len(hcols))})', [hrow[c] for c in hcols])
            db.execute('insert into output_channel (unique_id, output_id, channel, name, '
                       'custom_options) values (?, ?, 0, ?, ?)',
                       (str(uuid.uuid5(NS, hid + '-ch0')), hid, '', '{}'))
            acts.append({'id': 'Asim_heater', 'kind': 'heater', 'device_uuid': hid,
                         'specs': {'capacity_kw': a.heater_kw}, '_sim_virtual': True})
            made.append(('heater', hid))
        fittings = json.loads(fac['fittings'] or '[]') or []
        if not a.no_solar:
            made.append(('solar', _add_solar_channel(db, fittings, a.facility)))
        db.execute('update geo_facility set envelope = ?, actuators = ?, fittings = ? '
                   'where unique_id = ?',
                   (json.dumps(env, ensure_ascii=False), json.dumps(acts, ensure_ascii=False),
                    json.dumps(fittings, ensure_ascii=False), a.facility))
        db.commit()
    finally:
        db.close()
    for k, oid in made:
        kind = ('outdoor radiation (W/m²)' if k == 'solar'
                else f'on/off {a.heater_kw:.0f} kW' if k == 'heater'
                else 'binary' if a.binary else f'travel {a.travel:.0f}s')
        print(f'{k:22s} {oid}  {kind}')
    print(f'→ {a.dst}')


if __name__ == '__main__':
    main()
