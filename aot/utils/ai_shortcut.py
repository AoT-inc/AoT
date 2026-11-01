# coding=utf-8
"""AI 바로가기 주소(settings > 일반) 검사 (2026-10-22).

휴대폰 AI 창구의 [Claude] 같은 단추가 새 탭으로 여는 주소다. 사용자가 정하는 값이라 서버가 아는 서비스 목록은
없고(라벨 이름 붙이기는 화면 쪽), 위험한 모양만 막는다: https 만, 사용자 정보(user:pass@) 없음, IP 주소·
점 없는 호스트 없음, 길이 ≤ 512. 빈 값은 "단추 없음"이다.
"""
import ipaddress
from urllib.parse import urlsplit

MAX_LEN = 512
DEFAULT = 'https://claude.ai/new'


def normalize(raw):
    """입력 → 저장할 주소(빈 문자열 = 단추 없음). 모양이 틀리면 ValueError."""
    text = (raw or '').strip()
    if not text:
        return ''
    if len(text) > MAX_LEN or any(ch in text for ch in ' \t\r\n"\'<>`\\'):
        raise ValueError('invalid')
    try:
        parts = urlsplit(text)
        host = parts.hostname or ''
        parts.port   # 잘못된 포트는 여기서 ValueError
    except ValueError:
        raise ValueError('invalid') from None
    if parts.scheme != 'https' or parts.username or parts.password or '.' not in host:
        raise ValueError('invalid')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return text
    raise ValueError('invalid')       # IP 주소 직접 입력 불가
