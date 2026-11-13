# coding=utf-8
"""앱 컨텍스트 없는 프로세스(데몬)에서 장소·농장 시각이 UTC 로 뭉개지지 않는다.

`Misc.query`·`GeoShape.query` 는 앱 컨텍스트가 없으면 실패한다. 예전 해석 길은 그
실패를 삼키고 UTC/시스템으로 떨어졌고, 로컬이 전부 +09:00 이라 가려졌다.
서브프로세스 둘: 하나는 임시 DB 를 만들고(앱 컨텍스트 있음), 하나는 컨텍스트 없이
읽는다. 임시 `AOT_LOCAL_DIR` 만 쓰므로 운영 DB 는 열리지 않는다.
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

SEED = r'''
from flask import Flask
from aot.config import AOT_DB_PATH
from aot.aot_flask.extensions import db
import aot.databases.models as m
from aot.databases.models.misc import Misc
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = AOT_DB_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
with app.app_context():
    db.create_all()
    misc = Misc.query.first() or Misc()
    misc.timezone = 'America/New_York'
    db.session.add(misc)
    # 장치 행의 tz 캐시는 읽지 않는다(결정 ①) — 시간대는 **자리**에서 온다:
    # 콜카타 대지 안 마커에 장치를 바인딩한다.
    from datetime import timedelta
    from aot.utils.timekit import utc_now
    db.session.add(m.Input(unique_id='dev-kolkata', name='t'))
    db.session.add(m.GeoMap(unique_id='map-k', name='k'))
    ring = [[77.0, 28.0], [77.2, 28.0], [77.2, 28.2], [77.0, 28.2], [77.0, 28.0]]
    db.session.add(m.GeoShape(unique_id='site-k', geo_id='map-k', type='site',
                              timezone='Asia/Kolkata', feature={
        'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [ring]},
        'properties': {'name': 'k'}}))
    db.session.add(m.GeoShape(unique_id='mk-k', geo_id='map-k', type='aot_device', feature={
        'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [77.1, 28.1]},
        'properties': {}}))
    db.session.add(m.GeoBinding(spatial_kind='shape', spatial_id='mk-k', role='marker',
                                device_kind='input', device_id='dev-kolkata',
                                channel_id='0',
                                valid_from=utc_now() - timedelta(days=1)))
    db.session.commit()
'''

PROBE = r'''
import json
from datetime import datetime, timezone
from flask import has_app_context, has_request_context
from aot.utils import timekit as tk
assert not has_app_context() and not has_request_context()
tz, src = tk.resolve_tz('dev-kolkata')
x = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
print(json.dumps({
    'tz': tz.zone, 'src': src,
    'farm_iso': tk.iso_at(x, tk.FARM),
    'miss_iso': tk.iso_at(x, 'no-such-id'),
    'dev_iso': tk.iso_at(x, 'dev-kolkata'),
}))
'''


def _run(code, local_dir):
    env = dict(os.environ, AOT_LOCAL_DIR=local_dir, ALEMBIC_RUNNING='1', PYTHONPATH=REPO)
    return subprocess.run([sys.executable, '-c', code], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)


def test_daemon_like_process_resolves_place_and_farm():
    with tempfile.TemporaryDirectory(prefix='aot-tk-') as d:
        seed = _run(SEED, d)
        assert seed.returncode == 0, seed.stderr[-2000:]
        probe = _run(PROBE, d)
        assert probe.returncode == 0, probe.stderr[-2000:]
        out = json.loads(probe.stdout.strip().splitlines()[-1])
    assert out['src'] != 'system', out        # 이번 결함: 컨텍스트 없으면 'system'/UTC 로 뭉개졌다
    assert out['tz'] == 'Asia/Kolkata'
    assert out['dev_iso'].endswith('+05:30')
    assert out['farm_iso'].endswith('-04:00')  # 7월 뉴욕 = 농장
    assert out['miss_iso'].endswith('-04:00')  # 못 찾은 id → 농장
