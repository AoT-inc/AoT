# coding=utf-8
"""스냅샷 (설계 §7 제안 A). Open API 에는 정지 이미지가 없다.

1) 라이브 허브가 돌고 있으면 마지막 프레임 파일(3초 이내)을 쓴다 — 새 연결도 새 인증도 없다.
2) 아니면 /stream6(MJPEG)을 한 번 열어 첫 JPEG 를 받고 바로 닫는다.
3) 래치가 걸려 있으면 시도하지 않는다(소스가 거부한다).
"""
from aot.camera_drivers import frames as F


class SnapshotError(Exception):
    pass


def take_snapshot(camera_id, source_factory, max_age=3.0, directory=None, read_attempts=5):
    """JPEG bytes. 실패하면 SnapshotError(사유). `source_factory()` 는 mjpeg 프로파일의 FrameSource."""
    data = F.LatestFrameFile.read_fresh(camera_id, max_age=max_age, directory=directory)
    if data:
        return data
    src = source_factory()
    try:
        try:
            src.open()
        except F.SourceError as exc:
            raise SnapshotError(exc.reason)
        for _ in range(read_attempts):
            frame = src.read()
            if frame is not None and frame.jpeg:
                return frame.jpeg
        raise SnapshotError('no_frame')
    finally:
        src.close()
