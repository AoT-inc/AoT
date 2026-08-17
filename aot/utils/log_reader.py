# coding=utf-8
"""로그 소스 레지스트리 + 안전한 tail/파싱/필터.

기존 `/logview` 는 사용자가 넣은 검색어를 그대로 셸 파이프라인에 이어 붙여
(`tail -n N file | grep "<search>"`, `shell=True`) 실행했다. `view_logs` 권한을
가진 사람이 검색창에 `"; <임의명령> #` 을 넣으면 그대로 실행된다 — 로그를 볼
권한이 셸 실행 권한이 되어 버린다. 이 모듈은 셸을 아예 쓰지 않는다:
파일은 파이썬으로 직접 읽고, 외부 명령은 argv 리스트로만 실행하며, 검색과
레벨 필터는 읽어 온 텍스트 위에서 파이썬이 수행한다.

읽기 방식이 tail-then-filter 가 아니라 **뒤에서부터 창을 넓혀 가며 스캔**인
이유: 'AI' 처럼 한 파일(aot.log) 안에서 로거 이름으로 걸러내는 소스는 마지막
N줄만 읽으면 매칭이 0건일 수 있다. 원하는 만큼 모일 때까지 창을 두 배씩
넓히되 상한(_SCAN_WINDOW_MAX)에서 멈추고 `truncated` 로 알린다.
"""
import os
import re
import shutil
import subprocess

from aot.config import (BACKUP_LOG_FILE, DAEMON_LOG_FILE, DEPENDENCY_LOG_FILE,
                        DOCKER_CONTAINER, HTTP_ACCESS_LOG_FILE,
                        HTTP_ERROR_LOG_FILE, IMPORT_LOG_FILE, KEEPUP_LOG_FILE,
                        LOGIN_LOG_FILE, MCP_LOG_FILE, RESTORE_LOG_FILE,
                        UPGRADE_LOG_FILE)

# 최소 레벨 필터의 순위. 레벨을 못 읽은 줄은 rank 0 이라 어떤 최소 레벨에도
# 걸리지 않는다 — 자세한 근거는 filter_entries() 참조.
LEVEL_RANK = {
    'DEBUG': 10,
    'INFO': 20,
    'WARNING': 30,
    'WARN': 30,
    'ERROR': 40,
    'CRITICAL': 50,
    'FATAL': 50,
    'EXCEPTION': 40,
}

LEVEL_CHOICES = ('DEBUG', 'INFO', 'WARNING', 'ERROR')

# 한 번에 읽는 창의 시작 크기와 상한. 상한은 aot.log(수십 MB)를 통째로 들고
# 오지 않기 위한 것이다 — 창을 넓히는 것은 필터가 걸린 소스에서만 의미가 있고,
# 그마저도 16MB 면 대개 며칠치다.
_SCAN_WINDOW_START = 256 * 1024
_SCAN_WINDOW_MAX = 16 * 1024 * 1024

# 증분 읽기에서 한 번에 받아들이는 최대 신규 바이트. 이보다 많이 밀렸으면
# 증분을 포기하고 일반 tail 로 되돌아간다(로그 폭주 시 응답이 수십 MB 가 되는
# 것을 막는다).
_INCREMENTAL_MAX = 4 * 1024 * 1024

_MAX_LINES = 2000
_DEFAULT_LINES = 200

_COMMAND_TIMEOUT = 15

# `%(asctime)s - %(levelname)s - %(name)s - %(message)s`
# (aot/utils/logging_setup.py, aot_daemon.py 의 공통 포맷)
_RE_AOT = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)'
    r'\s+-\s+(?P<level>[A-Z]+)\s+-\s+(?P<logger>\S+)\s+-\s?(?P<msg>.*)$')

# `%(asctime)s %(name)s %(levelname)s %(message)s` (aot_mcp_server.py)
_RE_MCP = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)'
    r'\s+(?P<logger>\S+)\s+(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)'
    r'\s+(?P<msg>.*)$')

# 타임스탬프로 시작하기만 하는 줄(= 새 항목의 시작). 이걸로 갈라야 파이썬
# 트레이스백처럼 여러 줄인 항목이 조각나지 않는다.
_RE_TS_HEAD = re.compile(
    r'^\[?(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}'
    r'|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3} - )')

# 형식을 모르는 로그에서 레벨만 건져내기 위한 보조 탐지.
_RE_LOOSE_LEVEL = re.compile(
    r'\b(CRITICAL|FATAL|ERROR|EXCEPTION|WARNING|WARN|INFO|DEBUG)\b')


# ---------------------------------------------------------------------------
# 소스 레지스트리
# ---------------------------------------------------------------------------

def _journal_or_docker(unit, container):
    """네이티브 설치면 journalctl, 도커면 `docker logs` argv 를 돌려준다.

    도커 배포의 앱 컨테이너에는 docker CLI 도 소켓도 없다(실측). 예전 코드는
    그걸 모르고 `docker logs ...` 를 셸로 돌려 로그 자리에
    `sh: 1: docker: not found` 를 보여 줬다 — 로그가 비었는지 명령이 없는지
    구분되지 않는다. 여기서는 실행 파일 유무를 먼저 보고, 없으면 available
    False 로 내려 UI 가 이유를 말하게 한다.
    """
    if DOCKER_CONTAINER:
        return {'kind': 'command',
                'argv': ['docker', 'logs', '--tail', '{lines}', container],
                'binary': 'docker'}
    return {'kind': 'command',
            'argv': ['journalctl', '-u', unit, '-n', '{lines}', '--no-pager'],
            'binary': 'journalctl'}


def _file(path, **kwargs):
    src = {'kind': 'file', 'path': path}
    src.update(kwargs)
    return src


class OrderedSources(object):
    """id → 정의. 선언 순서를 그대로 UI 순서로 쓴다."""

    def __init__(self):
        self._order = []
        self._map = {}

    def add(self, source_id, label, category, spec):
        spec = dict(spec)
        spec['id'] = source_id
        spec['label'] = label
        spec['category'] = category
        self._order.append(source_id)
        self._map[source_id] = spec

    def __contains__(self, source_id):
        return source_id in self._map

    def get(self, source_id):
        return self._map.get(source_id)

    def all(self):
        return [self._map[i] for i in self._order]


def _build_registry():
    """소스 정의. LOG_PATH 가 런타임에 정해지므로 import 시점에 고정하지 않는다."""
    reg = OrderedSources()

    # --- AI / MCP -----------------------------------------------------
    # AI 서비스는 자기 파일을 갖지 않는다. `logging.getLogger('aot.ai.…')` 가
    # 공용 'aot' 로거로 전파돼 aot.log 한 곳에 섞여 쌓인다. 그래서 별도
    # 파일을 만드는 대신 같은 파일을 로거 이름으로 걸러 하나의 소스로 세운다.
    reg.add('ai', 'AI', 'ai',
            _file(DAEMON_LOG_FILE, logger_prefixes=('aot.ai',)))
    reg.add('mcp', 'MCP Server', 'ai', _file(MCP_LOG_FILE))

    # --- 시스템 --------------------------------------------------------
    reg.add('daemon', 'Daemon', 'system', _file(DAEMON_LOG_FILE))
    reg.add('pid_settings', 'Daemon (PID settings)', 'system',
            _file(DAEMON_LOG_FILE, contains='PID Settings'))
    reg.add('keepup', 'Daemon keepup', 'system', _file(KEEPUP_LOG_FILE))

    # --- 웹 ------------------------------------------------------------
    # 'Web app' 은 gunicorn 프로세스의 'aot.aot_flask.*' 로거다. 도커에서
    # `docker logs aot_flask` 가 불가능한 배포에서도 웹 앱 로그를 볼 수 있는
    # 유일한 경로다(logging_setup 이 파일 핸들러를 붙인 뒤로 가능해졌다).
    reg.add('web_app', 'Web app', 'web',
            _file(DAEMON_LOG_FILE, logger_prefixes=('aot.aot_flask',)))
    reg.add('login', 'Web login', 'web', _file(LOGIN_LOG_FILE))
    reg.add('http_access', 'Web access', 'web', _file(HTTP_ACCESS_LOG_FILE))
    reg.add('http_error', 'Web error', 'web', _file(HTTP_ERROR_LOG_FILE))
    reg.add('flask', 'Web', 'web', _journal_or_docker('aotflask', 'aot_flask'))
    reg.add('nginx', 'Nginx', 'web', _journal_or_docker('nginx', 'aot_nginx'))

    # --- 유지보수 ------------------------------------------------------
    reg.add('dependency', 'Dependency', 'maintenance',
            _file(DEPENDENCY_LOG_FILE))
    reg.add('import', 'Import settings', 'maintenance', _file(IMPORT_LOG_FILE))
    reg.add('backup', 'AoT backup', 'maintenance', _file(BACKUP_LOG_FILE))
    reg.add('restore', 'AoT restore', 'maintenance', _file(RESTORE_LOG_FILE))
    reg.add('upgrade', 'AoT upgrade', 'maintenance', _file(UPGRADE_LOG_FILE))

    return reg


# 카테고리 표시 순서. 새 카테고리를 쓰면 여기에도 넣을 것 — 빠지면 그 소스는
# 목록 맨 뒤에 카테고리 없이 붙는다.
CATEGORY_ORDER = ('ai', 'system', 'web', 'maintenance')
CATEGORY_LABELS = {
    'ai': 'AI',
    'system': 'System',
    'web': 'Web',
    'maintenance': 'Maintenance',
}

DEFAULT_SOURCE = 'daemon'


def get_source(source_id):
    return _build_registry().get(source_id)


def list_sources():
    """UI 용 소스 목록. 각 항목에 available/이유를 채워 돌려준다.

    `reason` 은 완성된 문장이 아니라 `(사유키, 인자)` 다 — 문장을 여기서
    조립해 버리면 이미 값이 박힌 문자열이 되어 번역 카탈로그에서 찾을 수
    없다(`gettext("Command not available: docker")` 는 영원히 미번역이다).
    """
    out = []
    for spec in _build_registry().all():
        available, reason = _availability(spec)
        out.append({
            'id': spec['id'],
            'label': spec['label'],
            'category': spec['category'],
            'available': available,
            'reason': reason,
            'origin': _origin(spec),
        })
    return out


# _availability() 가 돌려주는 사유 키.
REASON_FILE_MISSING = 'file_missing'
REASON_COMMAND_MISSING = 'command_missing'


def _availability(spec):
    if spec['kind'] == 'file':
        path = spec['path']
        if os.path.isfile(path) or os.path.isfile(path + '.1'):
            return True, None
        return False, (REASON_FILE_MISSING, None)
    binary = spec.get('binary')
    if binary and not shutil.which(binary):
        # 명령이 없는 것과 로그가 빈 것은 다르다. 여기서 갈라 두지 않으면
        # 화면에서 구분할 수 없다.
        return False, (REASON_COMMAND_MISSING, binary)
    return True, None


def _origin(spec):
    if spec['kind'] == 'file':
        return spec['path']
    return ' '.join(a for a in spec['argv'] if a != '{lines}')


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

def parse_lines(lines):
    """원문 줄 목록 → 항목 목록. 타임스탬프 없는 줄은 직전 항목에 이어 붙인다."""
    entries = []
    for line in lines:
        if not line:
            continue
        parsed = _parse_line(line)
        if parsed is None and entries:
            # 트레이스백 등 이어지는 줄. 레벨/로거는 첫 줄 것을 그대로 쓴다.
            prev = entries[-1]
            prev['raw'] += '\n' + line
            prev['message'] += '\n' + line
            continue
        if parsed is None:
            parsed = {'ts': '', 'level': _loose_level(line), 'logger': '',
                      'message': line, 'raw': line}
        entries.append(parsed)
    return entries


def _parse_line(line):
    match = _RE_AOT.match(line)
    if match:
        return {'ts': match.group('ts'),
                'level': _normalize_level(match.group('level')),
                'logger': match.group('logger'),
                'message': match.group('msg'),
                'raw': line}
    match = _RE_MCP.match(line)
    if match:
        return {'ts': match.group('ts'),
                'level': _normalize_level(match.group('level')),
                'logger': match.group('logger'),
                'message': match.group('msg'),
                'raw': line}
    if _RE_TS_HEAD.match(line):
        return {'ts': '', 'level': _loose_level(line), 'logger': '',
                'message': line, 'raw': line}
    return None


def _normalize_level(level):
    level = (level or '').upper()
    if level == 'WARN':
        return 'WARNING'
    if level in ('FATAL',):
        return 'CRITICAL'
    return level if level in LEVEL_RANK else ''


def _loose_level(line):
    match = _RE_LOOSE_LEVEL.search(line[:120])
    return _normalize_level(match.group(1)) if match else ''


def _level_rank(entry):
    return LEVEL_RANK.get(entry.get('level') or '', 0)


# ---------------------------------------------------------------------------
# 필터
# ---------------------------------------------------------------------------

def filter_entries(entries, search='', min_level='', logger_prefixes=None,
                   contains=None):
    """읽어 온 항목에 검색어·최소레벨·로거 접두사·부분문자열 필터를 적용한다."""
    search = (search or '').lower()
    min_rank = LEVEL_RANK.get((min_level or '').upper(), 0)
    out = []
    for entry in entries:
        if logger_prefixes and not _logger_matches(entry, logger_prefixes):
            continue
        if contains and contains not in entry['raw']:
            continue
        if min_rank:
            # 레벨을 못 읽은 항목(rank 0)은 어떤 최소 레벨에도 안 걸린다.
            # login.log 처럼 레벨 개념이 없는 로그에서 레벨 필터를 걸면 결과가
            # 0건이 되는데, 그것이 정직한 답이다 — "그 로그에는 ERROR 급으로
            # 표시된 줄이 없다". 없는 레벨을 추측해 통과시키면 필터가 거짓말을
            # 한다. nginx error.log 처럼 줄 안에 레벨 낱말이 있는 형식은
            # _loose_level() 이 이미 건져 낸다.
            if _level_rank(entry) < min_rank:
                continue
        if search and search not in entry['raw'].lower():
            continue
        out.append(entry)
    return out


def _logger_matches(entry, prefixes):
    logger = entry.get('logger') or ''
    for prefix in prefixes:
        if logger == prefix or logger.startswith(prefix + '.'):
            return True
    return False


# ---------------------------------------------------------------------------
# 읽기
# ---------------------------------------------------------------------------

def read_log(source_id, lines=_DEFAULT_LINES, search='', min_level='',
             offset=None):
    """한 소스를 읽어 구조화된 결과를 돌려준다.

    Args:
        source_id: 레지스트리 id.
        lines: 돌려줄 최대 항목 수(필터 적용 후 기준).
        search: 대소문자 무시 부분 문자열.
        min_level: 'DEBUG'|'INFO'|'WARNING'|'ERROR' 중 하나 또는 빈 문자열.
        offset: 증분 읽기 기준 바이트 위치(파일 소스 전용). None 이면 전체 tail.

    Returns:
        dict — 'entries' 는 항상 시간 순(오래된 것 → 최신).
    """
    spec = get_source(source_id)
    if spec is None:
        return _error_result(source_id, 'Unknown log source')

    try:
        lines = max(1, min(int(lines), _MAX_LINES))
    except (TypeError, ValueError):
        lines = _DEFAULT_LINES

    available, reason = _availability(spec)
    if not available:
        result = _error_result(source_id, reason)
        result['label'] = spec['label']
        result['origin'] = _origin(spec)
        return result

    if spec['kind'] == 'file':
        return _read_file_source(spec, lines, search, min_level, offset)
    return _read_command_source(spec, lines, search, min_level)


def _error_result(source_id, message):
    return {
        'source': source_id,
        'label': source_id,
        'origin': '',
        'available': False,
        'error': message,
        'entries': [],
        'offset': None,
        'truncated': False,
        'incremental': False,
    }


def _read_file_source(spec, lines, search, min_level, offset):
    path = spec['path']
    logger_prefixes = spec.get('logger_prefixes')
    contains = spec.get('contains')

    if offset is not None:
        incremental = _read_incremental(path, offset)
        if incremental is not None:
            text, new_offset = incremental
            entries = filter_entries(
                parse_lines(text.splitlines()), search, min_level,
                logger_prefixes, contains)
            return {
                'source': spec['id'],
                'label': spec['label'],
                'origin': path,
                'available': True,
                'error': None,
                'entries': entries[-lines:],
                'offset': new_offset,
                'truncated': False,
                'incremental': True,
            }

    filtered, end_offset, truncated = _scan_backwards(
        path, lines, search, min_level, logger_prefixes, contains)

    return {
        'source': spec['id'],
        'label': spec['label'],
        'origin': path,
        'available': True,
        'error': None,
        'entries': filtered,
        'offset': end_offset,
        'truncated': truncated,
        'incremental': False,
    }


def _read_incremental(path, offset):
    """offset 이후 새로 붙은 내용만 읽는다. 못 쓰면 None(→ 전체 tail 폴백)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if offset < 0 or offset > size:
        # 로테이션·truncate. 옛 offset 은 의미가 없으므로 전체 tail 로 되돌린다.
        return None
    if size - offset > _INCREMENTAL_MAX:
        return None
    if size == offset:
        return '', size
    try:
        with open(path, 'rb') as handle:
            handle.seek(offset)
            data = handle.read(size - offset)
    except OSError:
        return None
    return data.decode('utf-8', 'replace'), size


def _scan_backwards(path, lines, search, min_level, logger_prefixes, contains):
    """필요한 만큼 창을 넓혀 가며 뒤에서부터 읽어 필터를 만족하는 항목을 모은다."""
    window = _SCAN_WINDOW_START
    filtered = []
    end_offset = None
    truncated = False

    while True:
        text, end_offset, reached_start = _tail_text(path, window)
        entries = parse_lines(text.splitlines())
        filtered = filter_entries(entries, search, min_level, logger_prefixes,
                                  contains)
        if len(filtered) >= lines or reached_start or window >= _SCAN_WINDOW_MAX:
            truncated = (len(filtered) < lines and not reached_start)
            break
        window *= 2

    return filtered[-lines:], end_offset, truncated


def _tail_text(path, want_bytes):
    """파일 끝에서 want_bytes 를 읽는다.

    로테이션된 `.1` 이 있고 창이 현재 파일 전체를 덮고도 남으면 그 앞부분을
    이어 붙인다 — 방금 로테이트된 직후에 화면이 비는 것을 막는다.

    Returns: (text, 현재 파일의 끝 오프셋, 창이 파일 시작에 닿았는지)
    """
    text = ''
    size = 0
    remaining = want_bytes

    if os.path.isfile(path):
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        start = max(0, size - remaining)
        try:
            with open(path, 'rb') as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            data = b''
        if start > 0:
            newline = data.find(b'\n')
            data = data[newline + 1:] if newline != -1 else b''
        text = data.decode('utf-8', 'replace')
        remaining -= (size - start)
        reached_start = (start == 0)
    else:
        reached_start = True

    rotated = path + '.1'
    if reached_start and remaining > 0 and os.path.isfile(rotated):
        try:
            rot_size = os.path.getsize(rotated)
            rot_start = max(0, rot_size - remaining)
            with open(rotated, 'rb') as handle:
                handle.seek(rot_start)
                rot_data = handle.read()
            if rot_start > 0:
                newline = rot_data.find(b'\n')
                rot_data = rot_data[newline + 1:] if newline != -1 else b''
                reached_start = False
            text = rot_data.decode('utf-8', 'replace') + text
        except OSError:
            pass

    return text, size, reached_start


def _read_command_source(spec, lines, search, min_level):
    # argv 리스트 + shell=False. 사용자 입력(search)은 여기 들어가지 않는다 —
    # 검색은 읽어 온 뒤 파이썬이 한다.
    argv = [str(lines) if arg == '{lines}' else arg for arg in spec['argv']]
    try:
        proc = subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=_COMMAND_TIMEOUT, shell=False)
        text = proc.stdout.decode('utf-8', 'replace')
    except subprocess.TimeoutExpired:
        return _error_result(spec['id'], 'Timed out reading this log source')
    except OSError as err:
        return _error_result(spec['id'], str(err))

    entries = filter_entries(parse_lines(text.splitlines()), search, min_level)
    return {
        'source': spec['id'],
        'label': spec['label'],
        'origin': _origin(spec),
        'available': True,
        'error': None,
        'entries': entries[-lines:],
        'offset': None,
        'truncated': False,
        'incremental': False,
    }
