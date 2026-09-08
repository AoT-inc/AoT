# coding=utf-8
"""Sentinel Hub 레이어 — 자격증명 노출·타일 좌표·캐시 키 (2026-09-07).

## 왜 만들었나

기존 NDVI 는 MODIS 250m 뿐이라 필지 하나가 화소 하나에 들어갔다. Sentinel-2
는 10m 지만, 대신 **OAuth2 client credentials** 를 쓴다 — 다른 타일 레이어처럼
URL 에 키를 박으면 client_secret 이 브라우저로 나간다.

## 이 테스트가 지키는 것

**① 자격증명이 브라우저로 나가지 않는다.** 레이어 URL 은 서버 프록시를
가리켜야 한다. 이것이 이 모듈의 존재 조건이라 회귀하면 즉시 사고다.

**② 캐시 키가 하루 동안 고정된다.** 요청 시간 범위를 `now` 로 잡으면 매 초
다른 요청이 되어 타일 캐시가 영영 안 맞는다 — 무료 등급 30,000 PU 를 그냥
태우게 된다. 그래서 날짜 경계로 끊는다.

**③ 관측 없는 화소는 투명하다.** 지수 evalscript 가 `dataMask` 를 알파로
쓰지 않으면 구름·궤도 밖이 "지수가 매우 낮은 땅" 으로 그려진다.

⚠ 네트워크를 쓰지 않는다.
"""
import pytest

from aot.inputs_gis import gis_sentinelhub as sh


class FakeDev:
    unique_id = 'layer-uid-1'
    name = 'Sentinel-2 NDVI'
    log_level_debug = False


def make_layer(**options):
    """DB 없이 설정된 레이어 인스턴스. 운영 경로와 같은 방식으로 옵션을 넣는다."""
    opts = {
        'client_id': 'CID', 'client_secret': 'SECRET',
        'active_channels': [0], 'collection': 'sentinel-2-l2a',
        'time_window_days': '30', 'max_cloud': '40',
        'mosaicking_order': 'leastCC',
    }
    opts.update(options)
    inst = sh.InputModule(FakeDev(), testing=True)
    # 운영에서는 AbstractInput 이 채워 주는 값. 타일·범례 URL 이 이걸 쓴다.
    inst.unique_id = FakeDev.unique_id
    inst.custom_options = opts
    inst.get_custom_option = lambda opt, default=None: opts.get(opt, default)
    return inst


class TestCredentialsStayServerSide:
    """① 이 모듈의 존재 조건."""

    def test_레이어_URL_이_프록시를_가리킨다(self):
        url = make_layer().get_url()
        assert url.startswith('/api/geo/proxy/sentinelhub/layer-uid-1'), url
        assert '{z}' in url and '{x}' in url and '{y}' in url

    def test_URL_에_자격증명이_없다(self):
        url = make_layer().get_url()
        assert 'SECRET' not in url and 'CID' not in url

    def test_범례에도_자격증명이_없다(self):
        legend = make_layer().get_legend()
        assert 'SECRET' not in legend['content']
        assert 'CID' not in legend['content']

    def test_상류_URL_을_템플릿에_두지_않는다(self):
        """default_url 에 상류를 적어 두면 언젠가 그대로 프런트로 나간다."""
        assert sh.INPUT_INFORMATION['default_url'] == ''

    def test_자격증명이_없으면_토큰을_요청하지_않는다(self):
        """네트워크를 타기 전에 걸러야 한다."""
        assert sh.get_access_token('', '') is None
        assert sh.get_access_token('CID', '') is None


class TestTimeRangeIsDayAligned:
    """② 캐시 키 안정성 — PU 예산이 여기 달려 있다."""

    def test_두_번_불러도_같다(self):
        assert sh.time_range(30) == sh.time_range(30)

    def test_자정_경계로_끊는다(self):
        start, end = sh.time_range(30)
        assert start.endswith('T00:00:00Z') and end.endswith('T00:00:00Z')

    def test_창_길이가_맞는다(self):
        from datetime import datetime
        start, end = sh.time_range(14)
        days = (datetime.strptime(end, '%Y-%m-%dT%H:%M:%SZ') -
                datetime.strptime(start, '%Y-%m-%dT%H:%M:%SZ')).days
        assert days == 15    # 시작일부터 '내일 00시' 까지 = 창 + 1

    def test_망가진_값에_기본_30일(self):
        from datetime import datetime
        for bad in (None, '', 'abc'):
            start, end = sh.time_range(bad)
            days = (datetime.strptime(end, '%Y-%m-%dT%H:%M:%SZ') -
                    datetime.strptime(start, '%Y-%m-%dT%H:%M:%SZ')).days
            assert days == 31, bad


class TestEvalscripts:
    """③ 관측 없는 화소는 투명해야 한다."""

    @pytest.mark.parametrize('channel_id', sorted(sh.CHANNELS))
    def test_모든_채널에_evalscript_가_있다(self, channel_id):
        script = sh.CHANNELS[channel_id]['options']['evalscript']
        assert script.startswith('//VERSION=3')
        assert 'function evaluatePixel' in script

    @pytest.mark.parametrize('channel_id', sorted(sh.CHANNELS))
    def test_알파에_dataMask_를_쓴다(self, channel_id):
        """없으면 구름·궤도 밖이 '값이 매우 낮은 땅' 으로 그려진다."""
        script = sh.CHANNELS[channel_id]['options']['evalscript']
        assert 's.dataMask]' in script, channel_id
        assert 'output: {bands: 4}' in script, channel_id

    def test_통계용_evalscript_는_출력_규약을_지킨다(self):
        """Statistical API 는 출력 id 가 `data` 이고 dataMask 출력이 필수다."""
        script = sh._index_stats_evalscript('B08', 'B04')
        assert 'id: "data"' in script
        assert 'id: "dataMask"' in script
        assert 'sampleType: "FLOAT32"' in script

    def test_값이_있는_채널만_범례_숫자를_단다(self):
        """트루컬러에는 요약할 숫자가 없다 — 범례에 '--' 만 남으면 안 된다."""
        for channel_id, info in sh.CHANNELS.items():
            has_index = bool(info['options'].get('index'))
            has_gradient = bool(info['options'].get('gradient'))
            assert has_index == has_gradient, channel_id
        assert make_layer(active_channels=[1]).get_legend() is None


class TestTileGeometry:
    """웹 메르카토르 타일 → BBOX."""

    def test_z0_은_전지구다(self):
        minx, miny, maxx, maxy = sh.tile_bbox_3857(0, 0, 0)
        assert minx == pytest.approx(-20037508.34, abs=0.1)
        assert maxy == pytest.approx(20037508.34, abs=0.1)
        assert maxx == -minx and miny == -maxy

    def test_z1_사분면(self):
        """x=1,y=0 은 북동 사분면(경도 0~180, 위도 0~85)."""
        minx, miny, maxx, maxy = sh.tile_bbox_3857(1, 1, 0)
        assert minx == pytest.approx(0, abs=0.1)
        assert miny == pytest.approx(0, abs=0.1)

    def test_이웃_타일이_맞닿는다(self):
        left = sh.tile_bbox_3857(12, 3494, 1584)
        right = sh.tile_bbox_3857(12, 3495, 1584)
        below = sh.tile_bbox_3857(12, 3494, 1585)
        assert left[2] == pytest.approx(right[0])
        assert left[1] == pytest.approx(below[3])

    def test_한국_지점이_제자리에_온다(self):
        """z12/3494/1584 는 서울 부근(경도 약 127, 위도 약 37.5)."""
        import math
        minx, miny, maxx, maxy = sh.tile_bbox_3857(12, 3494, 1584)
        lon = (minx + maxx) / 2 / 20037508.34 * 180
        lat_rad = math.atan(math.sinh(
            ((miny + maxy) / 2 / 20037508.34) * math.pi))
        assert 126.5 < lon < 127.5
        assert 37.0 < math.degrees(lat_rad) < 38.0


class TestBudgetGuards:
    """무료 등급 30,000 PU 를 지키는 장치들."""

    def test_광역_줌은_상류를_부르지_않는다(self):
        """라우트가 이 값 아래를 잘라낸다."""
        assert sh.MIN_ZOOM >= 8

    def test_타일_캐시_수명이_길다(self):
        """재방문 5일짜리 자료다 — 짧은 캐시는 같은 그림을 다시 사는 것이다."""
        assert make_layer().get_leaflet_options()['cache_seconds'] >= 3600

    def test_자동_새로고침을_걸지_않는다(self):
        assert make_layer().refresh_interval == 0


class TestRegistration:
    def test_필수_키가_있다(self):
        for key in ('input_name_unique', 'input_name', 'key_field',
                    'global_key_field', 'custom_options', 'layer_type'):
            assert key in sh.INPUT_INFORMATION, key

    def test_두_자격증명이_모두_필수로_선언돼_있다(self):
        """라우트의 형제 레이어 상속이 `required` 를 보고 동작한다."""
        required = {opt['id'] for opt in sh.INPUT_INFORMATION['custom_options']
                    if opt.get('required')}
        assert {'client_id', 'client_secret'} <= required


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
