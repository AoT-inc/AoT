# coding=utf-8
"""흙 채널 알아보기 — 23개 화면 언어의 흙·근권·배지 낱말, 낱말 경계, 모듈 이름 폴백.

그리고 `recent`(일지 계산)에 채널 이름을 실어도 **일지 숫자는 그대로**다.
"""
import pytest


def _S():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


@pytest.mark.parametrize('name', [
    'Soil Temperature', 'soil_temp', 'SoilTemp', 'Substrate EC', 'Rockwool slab',
    'Bodentemperatur', 'Erde Temp', 'Temperatura del suelo', 'Temperatura do solo',
    'Température du sol', 'Temperatura del suolo', 'Bodemtemperatuur',
    'grondtemperatuur', 'Jordtemperatur', 'jord temp', 'Temperatura gleby',
    'podłoże', 'dirvožemio temperatūra', 'talajhőmérséklet', 'Toprak sıcaklığı',
    'toprağın nemi', 'suhu tanah', 'nhiệt độ đất', 'Температура почвы',
    'температура ґрунту', 'температура земљишта', 'temperatura zemljišta',
    '토양온도', '지온', '배지 온도', '근권 온도', '土壌温度', '地温', '培地',
    '土壤温度', '基质温度', '地溫', 'อุณหภูมิดิน', 'मिट्टी का तापमान',
])
def test_soil_words_in_every_language(name):
    assert _S()._is_soil_text(name), name


@pytest.mark.parametrize('name', [
    'Solar radiation', 'solar', 'Air Temperature', 'Humidity', 'Soloist',
    'jordbær', 'Background noise', 'Console', '', None, '土曜日', 'Outside temp',
    'Erdgeschoss', 'Terrace', 'Groundwater level',
])
def test_lookalikes_are_not_soil(name):
    # 'Groundwater' 는 'ground' 낱말이 아니다(낱말 경계). 'Erdgeschoss'(1층)도.
    assert not _S()._is_soil_text(name), name


def test_the_word_list_is_one_constant():
    S = _S()
    assert isinstance(S._SOIL_CHANNEL_WORDS, tuple)
    assert 'sol' in S._SOIL_CHANNEL_WORDS and 'soil*' in S._SOIL_CHANNEL_WORDS


def test_an_empty_channel_name_falls_back_to_the_module_name(monkeypatch):
    from types import SimpleNamespace
    S = _S()
    S._module_channel_names_cache.clear()
    import aot.utils.inputs as inputs_mod
    monkeypatch.setattr(inputs_mod, 'parse_input_information', lambda *a, **k: {
        'SOILNODE': {'measurements_dict': {
            0: {'measurement': 'temperature', 'name': 'Air Temperature'},
            2: {'measurement': 'temperature', 'name': 'Soil Temperature'}}}})
    row = SimpleNamespace(device='SOILNODE')
    try:
        assert S._module_channel_name(row, 2) == 'Soil Temperature'
        assert S._is_soil_text(S._module_channel_name(row, 2))
        assert not S._is_soil_text(S._module_channel_name(row, 0))
        assert S._module_channel_name(None, 2) == ''
    finally:
        S._module_channel_names_cache.clear()


# ── 일지 숫자는 그대로 ──────────────────────────────────────────────────

def _buckets(with_channel):
    rows = []
    for day, (air, soil) in enumerate([(1.5, -0.5), (2.0, -1.0), (0.0, 0.5)]):
        env = []
        for ch, name, delta in ((0, 'Air Temperature', air), (2, 'Soil Temperature', soil)):
            row = {'measurement': 'temperature', 'device_id': 'dev-1', 'channel': ch,
                   'sensor': 'node-1', 'unit': 'C',
                   'targets_eval': [{'label': 'Day temp', 'when': 'day',
                                     'value': 22.0, 'delta': delta}]}
            if with_channel:
                row['channel_name'] = name
            env.append(row)
        rows.append({'key': '2026-09-%02d' % (day + 1), 'env': env})
    return rows


def _numbers(drift):
    keep = ('days', 'above', 'below', 'on_target', 'mean', 'min', 'max', 'one_way')
    return [(d['measurement'], d['when'], [tuple(s[k] for k in keep) for s in d['sensors']],
             tuple(d[k] for k in ('days', 'days_hi', 'above', 'above_hi', 'below',
                                  'below_hi', 'mean', 'mean_hi', 'min', 'max',
                                  'one_way', 'agree')))
            for d in drift]


def test_journal_drift_numbers_do_not_change_with_channel_names():
    from aot.aot_flask.geo.plot_journal.calc import target_drift
    with_names = target_drift(_buckets(True))
    without = target_drift(_buckets(False))
    assert _numbers(with_names) == _numbers(without)
    # 숫자 자체도 고정해 둔다(공기 채널 3일 중 2일 초과, 흙 채널 2일 미달).
    sensors = with_names[0]['sensors']
    assert [(s['days'], s['above'], s['below']) for s in sensors] == [(3, 2, 0), (3, 1, 2)]
    assert [s.get('channel_name') for s in sensors] == ['Air Temperature', 'Soil Temperature']
    assert all('channel_name' not in s for s in without[0]['sensors'])
