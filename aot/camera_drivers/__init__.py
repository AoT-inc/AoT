# coding=utf-8
"""제조사 중립 카메라 드라이버 틀. 설계 docs/design/vigi-camera-module.md §3.

경계: 이 패키지는 `aot.camera.*` 를 import 하지 않는다(옛 미완성 패키지, 26-11 에 지웠다).
카메라 종류 카탈로그는 `aot/utils/camera_types.py` 다.
"""
from aot.camera_drivers.driver import CameraDriver

_REGISTRY = {}


def register_driver(vendor, cls):
    """vendor 키 → Driver 클래스. 같은 키에 다른 클래스를 다시 등록하면 오류."""
    if not vendor:
        raise ValueError('vendor required')
    existing = _REGISTRY.get(vendor)
    if existing is not None and existing is not cls:
        raise ValueError('driver already registered for %r' % vendor)
    _REGISTRY[vendor] = cls
    return cls


def get_driver_class(vendor):
    return _REGISTRY.get(vendor)


def registered_vendors():
    return sorted(_REGISTRY)


__all__ = ['CameraDriver', 'register_driver', 'get_driver_class', 'registered_vendors']
