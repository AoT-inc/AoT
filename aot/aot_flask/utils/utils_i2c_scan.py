# coding=utf-8
"""I2C 버스 스캔 — 입력·출력 설정의 주소 칸 옆 검색 버튼이 쓴다.

`i2cdetect` 를 인자 목록으로 실행하고(셸을 거치지 않는다) 응답을 주소 목록으로
바꾼다. 네이티브 설치에서만 의미가 있다: Docker 에서는 웹 서버가 호스트의
버스를 보지 못하므로 "찾지 못함" 이 아니라 "지원 안 함" 으로 답한다.
"""
import glob
import re
import subprocess

_ROW = re.compile(r'^[0-9a-f]{2}:\s*(.*)$', re.IGNORECASE)
_CELL = re.compile(r'^(?:[0-9a-f]{2}|UU|--)$', re.IGNORECASE)


def parse_i2cdetect(output):
    """`i2cdetect -y N` 출력에서 응답한 주소를 뽑는다.

    반환: (found, in_use) — 둘 다 `'0x44'` 형식 문자열 목록. `UU` 는 커널
    드라이버가 이미 점유한 주소다.
    """
    found, in_use = [], []
    for line in (output or '').splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        row_base = int(line.strip()[:2], 16)
        for col, cell in enumerate(m.group(1).split()):
            if not _CELL.match(cell) or cell == '--':
                continue
            if cell.upper() == 'UU':
                in_use.append('0x%02x' % (row_base + col))
            else:
                found.append('0x%02x' % int(cell, 16))
    return found, in_use


def available_buses():
    """이 프로세스에서 보이는 I2C 버스 번호(오름차순)."""
    buses = []
    for path in glob.glob('/dev/i2c-*'):
        try:
            buses.append(int(path.rsplit('-', 1)[1]))
        except ValueError:
            continue
    return sorted(buses)


def scan_bus(bus, timeout=15):
    """버스 하나를 스캔한다. 실패는 예외 대신 `error` 코드로 돌려준다."""
    if bus not in available_buses():
        return {'ok': False, 'error': 'no_bus', 'bus': bus}
    try:
        proc = subprocess.run(['i2cdetect', '-y', str(bus)],
                              capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {'ok': False, 'error': 'no_tool', 'bus': bus}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'timeout', 'bus': bus}
    if proc.returncode != 0:
        return {'ok': False, 'error': 'failed', 'bus': bus,
                'detail': (proc.stderr or '').strip()[:200]}
    found, in_use = parse_i2cdetect(proc.stdout)
    return {'ok': True, 'bus': bus, 'addresses': found, 'in_use': in_use}
