# coding=utf-8
"""모의 서버를 별도 프로세스(컨테이너)로 띄운다 — 8084 스택을 건드리지 않고 화면 시험을 할 때 쓴다.

    python -m aot.tests.fixtures.vigi_mock --openapi-port 20443 --rtsp-port 554 [--variant pt]

시험 계정은 admin / 인자로 준 비밀번호(기본은 시험값). 실카메라·배포 서버와 무관한 가짜다.
"""
import argparse
import time

from aot.tests.fixtures.vigi_mock.rtsp import MockRtspServer
from aot.tests.fixtures.vigi_mock.server import MockVigiServer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--openapi-port', type=int, default=20443)
    ap.add_argument('--rtsp-port', type=int, default=554)
    ap.add_argument('--variant', default='pt', choices=['pt', 'fixed', 'zoom', 'full'])
    ap.add_argument('--password', default='correct-horse-battery')
    a = ap.parse_args()
    api = MockVigiServer(variant=a.variant, password=a.password, host=a.host, port=a.openapi_port).start()
    rtsp = MockRtspServer(password=a.password, host=a.host, port=a.rtsp_port).start()
    print('vigi-mock up: openapi=%d rtsp=%d variant=%s cert=%s' % (
        api.port, rtsp.port, a.variant, api.cert_sha256[:16]), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
