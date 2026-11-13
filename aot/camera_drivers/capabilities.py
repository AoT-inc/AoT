# coding=utf-8
"""능력 어휘(제조사 중립)와 Capabilities 값 객체. 설계 §3.2.

화면은 Capabilities 를 보고 그 기능을 아예 그리지 않는다. 제품별 하드코딩 표는 없다.
"""
import json

PTZ_PAN_TILT = 'ptz.pan_tilt'
PTZ_ZOOM = 'ptz.zoom'
PTZ_PRESET = 'ptz.preset'
DAY_NIGHT = 'day_night'
ALARM_SOUND = 'alarm.sound'
ALARM_LIGHT = 'alarm.light'
ALARM_MANUAL = 'alarm.manual'
AUDIO_SPEAKER = 'audio.speaker'
AUDIO_MIC = 'audio.mic'
STORAGE_SD = 'storage.sd'
EVENTS_PUSH = 'events.push'
RECORD_PLAYBACK = 'record.playback'
RECORD_DOWNLOAD = 'record.download'

# 이벤트 종류 어휘(중립). 'cv.' 접두사는 향후 영상 분석 이벤트용으로 예약한다.
EVENT_KINDS = (
    'motion', 'crossline', 'intrusion', 'area_entry', 'area_leave', 'people',
    'vehicle', 'drop_take', 'loiter', 'tamper', 'scene_change', 'audio_anomaly',
)
CV_PREFIX = 'cv.'
UNKNOWN_KIND = 'unknown'


def event_cap(kind):
    return 'event.' + kind


ENHANCE_PEOPLE = 'event.enhance.people'
ENHANCE_VEHICLE = 'event.enhance.vehicle'


class Capabilities:
    """기능 집합(문자열) + 수치 속성(speed_max, preset_max 등). 불변처럼 다룬다."""

    def __init__(self, features=(), attrs=None):
        self.features = frozenset(features)
        self.attrs = dict(attrs or {})

    def has(self, feature) -> bool:
        return feature in self.features

    def event_kinds(self):
        """지원하는 이벤트 종류(어휘 순서 유지)."""
        return [k for k in EVENT_KINDS if event_cap(k) in self.features]

    def attr(self, name, default=None):
        return self.attrs.get(name, default)

    def to_json(self) -> str:
        return json.dumps({'features': sorted(self.features), 'attrs': self.attrs},
                          ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, text):
        if not text:
            return cls()
        d = json.loads(text) if isinstance(text, str) else text
        return cls(d.get('features', ()), d.get('attrs'))

    def __eq__(self, other):
        return isinstance(other, Capabilities) and self.features == other.features \
            and self.attrs == other.attrs

    def __repr__(self):
        return 'Capabilities(%d features)' % len(self.features)
