# coding=utf-8
import importlib.util
import logging
import os
import threading
import traceback

logger = logging.getLogger("aot.modules")


def load_module_from_file(path_file, module_type):
    """Load a Python module from a file path using importlib.

    @phase active
    @stability stable
    """
    try:
        module_name = "aot.{}.{}".format(
            module_type, os.path.basename(path_file).split('.')[0])
        spec = importlib.util.spec_from_file_location(module_name, path_file)
        if spec is None or spec.loader is None:
            return None, f"Could not create spec for: {path_file}"
        module_custom = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module_custom)
        return module_custom, "success"
    except Exception:
        logger.error(f"Path: {path_file}, Type: {module_type}")
        logger.error(f"Could not load module: {traceback.format_exc()}")
        return None, traceback.format_exc()


#: 파일 지문(경로, 수정 시각, 크기, 종류) → 불러 둔 모듈. `load_module_from_file` 은 부를 때마다 파일을 다시 실행해 **새 모듈
#: 객체**를 만든다 — 모듈 전역에 둔 캐시(`gis_openweather._FORECAST_CACHE`, 토큰·폴리곤 캐시 …)가 부를 때마다 빈 새 사전이
#: 되어 한 번도 적중하지 못했다(2026-10-26: 예보 한 번에 같은 OpenWeather 요청이 40번, 첫 조회 21~28초).
_CACHED_MODULES = {}
_CACHED_LOCK = threading.Lock()


def load_module_cached(path_file, module_type):
    """`load_module_from_file` 과 같은 결과를 주되, **파일이 그대로면 같은 모듈 객체**를 돌려준다.

    모듈 전역 상태(캐시·락)를 그 모듈 인스턴스들이 나눠 쓰게 하려는 호출용이다. 파일을 고치거나 바꾸면(수정 시각·크기)
    지문이 달라져 새로 불러온다 — 사용자가 올린 커스텀 모듈을 고쳐도 반영된다. 실패는 캐시하지 않는다.
    쓰면 안 되는 곳: 부를 때마다 새 모듈 상태가 필요한 호출(그대로 `load_module_from_file`)."""
    try:
        st = os.stat(path_file)
        stamp = (os.path.realpath(path_file), st.st_mtime_ns, st.st_size, module_type)
    except OSError:
        return load_module_from_file(path_file, module_type)
    with _CACHED_LOCK:
        hit = _CACHED_MODULES.get(stamp)
    if hit is not None:
        return hit, "success"
    module, status = load_module_from_file(path_file, module_type)
    if module is None:
        return module, status
    with _CACHED_LOCK:
        # 같은 파일의 옛 지문 항목은 버린다(고친 파일이 쌓이지 않게). 동시에 둘이 불렀다면 먼저 넣은 것을 쓴다.
        for old in [k for k in _CACHED_MODULES if k[0] == stamp[0] and k != stamp]:
            _CACHED_MODULES.pop(old, None)
        module = _CACHED_MODULES.setdefault(stamp, module)
    return module, status
