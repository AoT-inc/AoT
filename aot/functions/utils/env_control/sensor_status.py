# coding=utf-8
"""옮겨 감: `aot/utils/sensor_status.py` (순수 계산이라 공간·모델 계층도 쓴다 — ARCHITECTURE.md §4 규칙 6).

설치본의 사용자 확장(`custom_functions`)이 옛 경로로 import 해도 같은 모듈 객체를 받도록
남긴 별칭이다. 저장소 안 코드는 새 경로만 쓴다.
"""
import sys

from aot.utils import sensor_status as _module

sys.modules[__name__] = _module
