# coding=utf-8
"""반입한 MapLibre GL JS 가 몇 버전인지, 그 버전이 무엇을 할 수 있는지 한 곳에서 답한다.

## 왜 있는가

버전 문자열 `4.1.2` 가 여섯 자리에 손으로 박혀 있었다 — layout 의 로컬/CDN 두
갈래, `map-loader.js` 의 네 자리. 5 를 나란히 두려면 그 여섯을 동시에 고쳐야
하고, 하나만 빠뜨리면 **CSS 는 4 인데 JS 는 5** 같은 상태가 조용히 만들어진다.

그래서 버전은 **반입 디렉터리가 정한다.** `static/vendor/maplibre-gl-<버전>/`
을 훑어 가장 높은 것을 고른다. `maplibre-gl-5.6.0/` 을 떨어뜨려 놓으면 그것이
곧 쓰이는 버전이고, 지우면 4 로 돌아간다. 손으로 고칠 곳은 없다.

## 능력 질의

버전을 아는 것만으로는 부족하다 — 부르는 쪽이 알고 싶은 것은 "이 기능을 켜도
되는가" 다. 그래서 `supports_terrain()` 처럼 **능력**으로 묻게 한다. 판정 근거는
그 함수의 주석에 적어 둔다. 같은 판정을 브라우저에서도 해야 하므로
`geo/aot-maplibre-patches.js` 의 `AoTMapLibreCaps` 가 같은 규칙을 되풀이한다 —
바꿀 때 둘을 함께 본다.
"""
import os
import re

_VENDOR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'aot_flask', 'static', 'vendor')

_DIR_RE = re.compile(r'^maplibre-gl-(\d+(?:\.\d+)*)$')

# 반입본을 하나도 못 찾았을 때의 답. 디렉터리가 통째로 빠진 설치에서도
# layout 이 렌더는 되어야 하므로(빈 경로를 뱉으면 404 조차 아니라 이상한
# URL 이 된다) 마지막으로 알려진 반입 버전을 쓴다.
_FALLBACK = '4.1.2'

_cache = {}


def _scan():
    found = []
    try:
        for name in os.listdir(_VENDOR):
            m = _DIR_RE.match(name)
            if not m:
                continue
            # 껍데기 디렉터리를 버전으로 세지 않는다.
            if not os.path.exists(os.path.join(_VENDOR, name, 'maplibre-gl.js')):
                continue
            found.append(m.group(1))
    except OSError:
        pass
    if not found:
        return _FALLBACK
    return max(found, key=lambda v: tuple(int(p) for p in v.split('.')))


def bundled_version():
    """반입한 MapLibre 의 버전 문자열. 예: '4.1.2'"""
    if 'version' not in _cache:
        _cache['version'] = _scan()
    return _cache['version']


def bundled_major():
    """반입한 MapLibre 의 메이저 번호. 예: 4"""
    try:
        return int(bundled_version().split('.')[0])
    except (ValueError, IndexError):
        return 0


def vendor_dir():
    """`static/vendor/` 아래 디렉터리 이름. 예: 'maplibre-gl-4.1.2'"""
    return 'maplibre-gl-' + bundled_version()


def supports_terrain():
    """3D 지형(`setTerrain`)을 켜도 되는가.

    **4 에서는 안 된다.** 4.1.2 로 실측한 결과(2026-09-06, 김제 지도):
    지형을 켜면 구획 외곽선(`line` 레이어)에서 아래로 늘어지는 세로선이
    그려진다. 그 픽셀에서 `queryRenderedFeatures` 는 아무것도 잡지 못한다 —
    도형이 아니라 그리기 단계의 찌꺼기다. 줌·베어링에 따라 나타났다 사라진다.
    고도 데이터를 제대로 넣어도(전 지구 DEM) 그대로였으므로 데이터가 아니라
    4 의 line+terrain 렌더 결함이다.

    그래서 5 가 반입되기 전까지 이 옵션은 설정 화면에 나오지 않고, 저장된
    값이 켜져 있어도 지도는 지형을 켜지 않는다.

    ⚠ 5 를 반입해 이 함수가 True 를 돌려주기 시작하면, **그 전에 DEM 소스를
    먼저 바꿔야 한다.** 지금 코드가 가리키는 `demotiles.maplibre.org/
    terrain-tiles` 는 이름이 `jaxa_terrainrgb_N047E011` 인 알프스 한 구역짜리
    데모 데이터다 — 국내 좌표는 z2 부터 전부 404 이고 고도가 어디서나 0 이다.
    즉 지형을 켜도 아무 일이 일어나지 않으면서 저작권 표시만 붙는다.
    """
    return bundled_major() >= 5
