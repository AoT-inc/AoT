# coding=utf-8
"""시험 전용 — 장치를 가리키는 마커·구역 도형과 그 현재 바인딩을 함께 만든다.

L4(C-4) 이후 위치의 정본은 geo_binding 뿐이다(`GeoShape.device_id` 컬럼은 읽지
않는다). 컬럼만 심은 옛 픽스처는 장치가 "배치되지 않은" 것으로 읽히므로,
시험은 바인딩을 함께 만든다. `device_kind` 를 모르면 실존하는 장치 표로 판별한다.
"""
from aot.space.device_binding import resolve_device_kind
from aot.databases.models import GeoBinding, GeoShape

_ROLES = {'aot_device': 'marker', 'device': 'area'}


def bound_shape(device_kind=None, **kw):
    """GeoShape(**kw) 를 저장하고, `device_id` 가 있으면 현재 바인딩도 만든다."""
    dev = (kw.pop('device_id', None) or '').split('::')[0]   # 컬럼은 p7_06 에서 사라졌다
    s = GeoShape(**kw)
    s.save()
    role = _ROLES.get(kw.get('type'))
    if dev and role:
        GeoBinding(spatial_kind='shape', spatial_id=s.unique_id, role=role,
                   device_kind=device_kind or resolve_device_kind(dev)
                   or 'output',
                   device_id=dev, channel_id=kw.get('channel_id') or '0').save()
    return s
