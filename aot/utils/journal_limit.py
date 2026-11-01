# -*- coding: utf-8 -*-
#
# journal_limit.py - systemd 저널(journald) 디스크 사용 상한.
#
# 저널은 상한을 따로 두지 않으면 파일시스템의 10% 까지 자란다(최대 4GiB).
# 실측(2026-10-19 aot-005): 110G 디스크에서 4.0G — AoT 본체(1.1G)의 네 배다.
# SD카드 32GB 짜리 라즈베리파이에서는 이 비율이 훨씬 아프다.
#
# 설정은 /etc/systemd/journald.conf.d/aot.conf 한 파일의 SystemMaxUse 하나다.
# 이 파일이 정본이고 DB 에는 저장하지 않는다 — 값의 주인은 journald 이고,
# 두 곳에 두면 갈라진다(DB 는 500M 인데 파일은 1G).
#
# 쓰기는 root 만 할 수 있고, 데몬(aot.service)이 root 로 돌므로 데몬이 맡는다
# (aot_daemon.PyroServer.journal_limit_apply). 웹(aotflask)은 읽기만 한다.
# setuid aot_wrapper 에 인자를 받는 명령을 더하지 않은 이유: 그 바이너리는
# 서버마다 재컴파일해야 하고, 인자가 쉘 문자열로 흘러 들어가는 구조다.
#
# 표준 라이브러리만 쓴다(데몬 기동 초기에 불린다).
#
import glob
import logging
import os
import re
import subprocess
import tempfile

from aot.utils.system_environment import is_docker

default_logger = logging.getLogger('aot.journal_limit')

DEFAULT_MB = 500
MIN_MB = 50
MAX_MB = 10240

CONF_DIR = '/etc/systemd/journald.conf.d'
CONF_PATH = os.path.join(CONF_DIR, 'aot.conf')
MAIN_CONF = '/etc/systemd/journald.conf'

_SIZE_RE = re.compile(r'^\s*([\d.]+)\s*([KMGT]?)(?:i?B)?\s*$', re.IGNORECASE)
_UNIT_MB = {'': 1.0 / (1024 * 1024), 'K': 1.0 / 1024, 'M': 1.0,
            'G': 1024.0, 'T': 1024.0 * 1024}


def parse_size_mb(text):
    """'500M' / '1G' / '4194304' (바이트) -> MB(float). 읽지 못하면 None."""
    match = _SIZE_RE.match(text or '')
    if not match:
        return None
    try:
        return float(match.group(1)) * _UNIT_MB[match.group(2).upper()]
    except (ValueError, KeyError):
        return None


def supported():
    """journald 를 이 프로세스가 다룰 수 있는 환경인가.

    Docker 컨테이너는 호스트의 저널이 아니라 자기 stdout 만 본다 — 여기서
    상한을 건드릴 수 있어 보여도 호스트 설정이 아니다.
    """
    if is_docker():
        return False
    return os.path.isdir('/run/systemd/system')


def _setting_in(path):
    """한 파일의 [Journal] SystemMaxUse 값(문자열). 없으면 None. 마지막 것이 이긴다."""
    try:
        with open(path, 'r', errors='ignore') as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    in_journal = False
    value = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('['):
            in_journal = line.lower() == '[journal]'
            continue
        if in_journal and '=' in line:
            key, _, val = line.partition('=')
            if key.strip() == 'SystemMaxUse':
                value = val.strip()
    return value


def _conf_files():
    """journald 가 읽는 순서(뒤가 이긴다)로 /etc 쪽 설정 파일."""
    files = [MAIN_CONF]
    files.extend(sorted(glob.glob(os.path.join(CONF_DIR, '*.conf')),
                        key=os.path.basename))
    return files


def effective_setting():
    """실제로 이기는 SystemMaxUse.

    반환: (mb 또는 None, 출처 파일 경로 또는 None). 어디에도 없으면 (None, None)
    — journald 기본값(파일시스템의 10%, 최대 4GiB)이 적용된다.
    """
    winner_mb, winner_path = None, None
    for path in _conf_files():
        raw = _setting_in(path)
        if raw is None:
            continue
        winner_mb, winner_path = parse_size_mb(raw), path
    return winner_mb, winner_path


def _foreign_setting():
    """우리 파일이 아닌 곳이 SystemMaxUse 를 정해 둔 경우 그 경로.

    사람이 직접 정한 값이다 — 기본값 적용이나 웹의 변경이 덮어쓰면 안 된다.
    (우리 파일보다 뒤에 읽히는 파일이 있으면 우리 값은 어차피 무효이기도 하다.)
    """
    for path in _conf_files():
        if os.path.abspath(path) == CONF_PATH:
            continue
        if _setting_in(path) is not None:
            return path
    return None


def disk_usage_mb():
    """현재 저널이 쓰는 용량(MB). 알 수 없으면 None."""
    try:
        out = subprocess.run(['journalctl', '--disk-usage'],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'take up\s+([\d.]+\s*[KMGT]?)', out or '')
    return parse_size_mb(match.group(1)) if match else None


def read_state():
    """웹 화면용 현재 상태. 읽기만 하므로 root 가 아니어도 된다."""
    if not supported():
        return {'supported': False}
    mb, path = effective_setting()
    own = os.path.abspath(path) == CONF_PATH if path else False
    return {
        'supported': True,
        'usage_mb': disk_usage_mb(),
        'limit_mb': mb,
        'limit_source': path,
        # 우리 파일이 아니면 웹에서 못 바꾼다 — 바꿔도 이기지 못하거나, 사람의 설정을 덮는다.
        'managed_elsewhere': bool(path) and not own,
        'default_mb': DEFAULT_MB,
        'min_mb': MIN_MB,
        'max_mb': MAX_MB,
    }


def validate_mb(value):
    """정수 MB 로 바꾸고 범위를 확인한다. 어긋나면 ValueError."""
    if isinstance(value, bool):
        raise ValueError('not an integer')
    mb = int(str(value).strip())
    if not MIN_MB <= mb <= MAX_MB:
        raise ValueError('out of range')
    return mb


def apply(mb, logger=None):
    """상한을 쓰고 즉시 적용한다. root 로 실행되어야 한다(데몬).

    반환: (ok, message). 예외를 올리지 않는다.
    """
    logger = logger or default_logger
    try:
        mb = validate_mb(mb)
    except (TypeError, ValueError):
        return False, 'invalid value'
    if not supported():
        return False, 'unsupported environment'
    foreign = _foreign_setting()
    if foreign:
        return False, 'managed elsewhere: {}'.format(foreign)

    content = ('# AoT 가 관리합니다 — 정보(System Information) 페이지에서 바꿉니다.\n'
               '[Journal]\nSystemMaxUse={}M\n').format(mb)
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=CONF_DIR, prefix='.aot.conf.')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(content)
            os.chmod(tmp, 0o644)
            os.replace(tmp, CONF_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as err:
        logger.error('journal_limit: cannot write %s: %s', CONF_PATH, err)
        return False, 'cannot write config: {}'.format(err)

    # 새 상한을 읽게 하고, 이미 넘은 만큼은 지금 비운다. 재시작만 하면
    # 상한은 다음 회전 때부터 효력이 생겨 용량이 한참 그대로 보인다.
    problems = []
    for cmd in (['systemctl', 'restart', 'systemd-journald'],
                ['journalctl', '--vacuum-size={}M'.format(mb)]):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                problems.append('{}: {}'.format(cmd[0], (proc.stderr or '').strip()))
        except (OSError, subprocess.SubprocessError) as err:
            problems.append('{}: {}'.format(cmd[0], err))
    if problems:
        # 설정 파일은 이미 써졌다 — 다음 journald 재시작 때 적용된다.
        logger.warning('journal_limit: saved %sM but apply step failed: %s',
                       mb, '; '.join(problems))
        return False, 'saved, but apply failed: {}'.format('; '.join(problems))
    logger.info('journal_limit: SystemMaxUse set to %sM', mb)
    return True, 'ok'


def ensure_default(logger=None):
    """상한이 어디에도 없으면 기본값(500M)을 건다. 있으면 건드리지 않는다.

    데몬 기동 때 부른다 — 기존 설치는 업그레이드 뒤 첫 기동에, 새 설치는 첫
    기동에 적용된다. 이미 값이 있으면(우리 것이든 사람 것이든) 그대로 둔다.
    반환: 실제로 걸었으면 True.
    """
    logger = logger or default_logger
    try:
        if not supported():
            return False
        mb, path = effective_setting()
        if path is not None:
            return False
        ok, message = apply(DEFAULT_MB, logger=logger)
        if not ok:
            logger.warning('journal_limit: default not applied: %s', message)
        return ok
    except Exception:
        logger.exception('journal_limit: ensure_default failed (non-fatal)')
        return False
