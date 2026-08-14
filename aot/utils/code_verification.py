# -*- coding: utf-8 -*-
import logging
import os
import sys

from markupsafe import Markup

from aot.config import INSTALL_DIRECTORY
from aot.config import PATH_PYTHON_CODE_USER
from aot.utils.system_pi import assure_path_exists
from aot.utils.system_pi import cmd_output
from aot.utils.system_pi import set_user_grp

logger = logging.getLogger(__name__)


def create_python_file(python_code_run, filename):
    assure_path_exists(PATH_PYTHON_CODE_USER)
    file_run = os.path.join(PATH_PYTHON_CODE_USER, filename)
    with open(file_run, 'w') as fw:
        fw.write('{}\n'.format(python_code_run))
        fw.close()
    set_user_grp(file_run, 'aot', 'aot')

    return python_code_run, file_run


# 사용자 코드 파일 이름 규약. 만드는 쪽과 지우는 쪽이 같은 표를 봐야 한다 —
# 예전에는 지우는 쪽이 세 파일에 인라인으로 흩어져 있었고, 그중 출력만 아무도
# 지우지 않았다.
USER_CODE_FILENAME = {
    'input': 'input_python_code_{}.py',
    'output': 'output_{}.py',
    'conditional': 'conditional_{}.py',
}


def delete_python_file(kind, unique_id):
    """장치가 지워질 때 그 장치의 사용자 코드 파일도 지운다.

    **삭제 경로를 새로 만들면 반드시 이 함수를 부를 것.** 안 부르면 파일만
    디스크에 남는데, 그 파일에는 장치 uuid 와 output_on/output_off 호출이
    그대로 들어 있다. DB 행이 없으니 실행되지는 않지만(데몬은 Output 행을 보고
    실행한다) 지워진 설비의 제어 코드가 남아 있는 것 자체가 위생 문제이고,
    같은 uuid 가 재사용되면 옛 코드가 되살아난다.

    2026-08-14 운영에서 발견: 출력 삭제 경로가 이 정리를 하나도 안 해
    `output_*.py` 3개가 고아로 남아 있었다. 그때 정리하던 곳은 5경로 중
    입력 단건·조건부 둘뿐이었고, 그마저 서로 다른 파일에 인라인이었다.

    파일이 없으면 조용히 넘어간다 — 코드를 한 번도 저장하지 않은 장치는
    파일 자체가 없는 것이 정상이다.
    """
    pattern = USER_CODE_FILENAME.get(kind)
    if not pattern or not unique_id:
        return False
    file_path = os.path.join(PATH_PYTHON_CODE_USER, pattern.format(unique_id))
    try:
        os.remove(file_path)
        return True
    except FileNotFoundError:
        return False
    except OSError as err:
        # 지우지 못한 것은 삼키지 않는다 — 조용히 남으면 다음 사람이 왜
        # 남았는지 알 방법이 없다. 다만 삭제 자체를 실패시키지는 않는다.
        logger.warning('사용자 코드 파일을 지우지 못했습니다 (%s): %s',
                       file_path, err)
        return False


def purge_orphan_user_code(min_age_sec=600):
    """기동 시 고아 사용자 코드 파일을 지운다 — 배포본이 스스로 낫는다.

    `user_python_code/` 의 파일은 장치(Input·Output·Conditional·CustomController)
    가 지워질 때 함께 지워져야 하는데, 출력 삭제 3경로가 그 정리를 하나도 하지
    않아 고아가 쌓였다(2026-08-14 운영에서 발견). 삭제 경로는 고쳤지만 **이미
    생긴 고아는 그것만으로 사라지지 않는다.** 운영자가 서버에 들어가 지우게
    하거나 사용자에게 안내하는 것은 해법이 아니다 — 코드가 만든 쓰레기는
    코드가 치운다.

    `_purge_corrupt_session_files` · `_prune_orphan_jobs` 와 같은 기동 자가정리다.

    안전장치 셋:
    - 이름 규약(`USER_CODE_FILENAME`)에 맞는 파일만 본다. 그 디렉터리의 다른
      파일은 건드리지 않는다.
    - DB 에 행이 살아 있으면 절대 지우지 않는다. 조회가 하나라도 실패하면
      **아무것도 지우지 않고** 반환한다 — 살아 있는 장치를 고아로 오판하는
      것이 남겨 두는 것보다 훨씬 나쁘다.
    - 방금 만들어진 파일(기본 10분)은 건너뛴다. 저장 도중 기동이 겹치는
      경우를 배제한다.
    """
    import time as _time

    try:
        if not os.path.isdir(PATH_PYTHON_CODE_USER):
            return

        from aot.databases.models import (Conditional, CustomController, Input,
                                          Output)
        live = set()
        for model in (Input, Output, Conditional, CustomController):
            rows = model.query.with_entities(model.unique_id).all()
            live.update(r[0] for r in rows if r[0])
        if not live:
            # 빈 설치이거나 조회가 비정상이다. 판단 근거가 없으므로 지우지 않는다.
            logger.debug("[Startup] 사용자 코드 정리: 장치가 하나도 없어 건너뜀")
            return

        now = _time.time()
        removed = []
        for filename in sorted(os.listdir(PATH_PYTHON_CODE_USER)):
            unique_id = None
            for pattern in USER_CODE_FILENAME.values():
                prefix, suffix = pattern.split('{}')
                if filename.startswith(prefix) and filename.endswith(suffix):
                    unique_id = filename[len(prefix):len(filename) - len(suffix)]
                    break
            if not unique_id or unique_id in live:
                continue

            path = os.path.join(PATH_PYTHON_CODE_USER, filename)
            try:
                if now - os.path.getmtime(path) < min_age_sec:
                    continue
                os.remove(path)
                removed.append(filename)
            except OSError as exc:
                logger.warning("[Startup] 고아 사용자 코드 삭제 실패 (%s): %s",
                               filename, exc)

        if removed:
            # 무엇을 지웠는지 반드시 남긴다 — 사용자가 "코드가 사라졌다" 고
            # 물었을 때 답할 근거가 로그밖에 없다.
            logger.info("[Startup] 지워진 장치의 사용자 코드 파일 %d개 정리: %s",
                        len(removed), ', '.join(removed))
    except Exception as exc:
        logger.warning("[Startup] 고아 사용자 코드 정리 실패: %s", exc)



def test_python_code(python_code_run, filename):
    """
    Function to evaluate the Python 3 code using pylint
    :param :
    :return: tuple (info, warning, success, error)
    """
    info = []
    warning = []
    success = []
    error = []

    try:
        python_code_run, file_run = create_python_file(python_code_run, filename)

        lines_code = ''
        for line_num, each_line in enumerate(python_code_run.splitlines(), 1):
            if len(str(line_num)) == 3:
                line_spacing = ''
            elif len(str(line_num)) == 2:
                line_spacing = ' '
            else:
                line_spacing = '  '
            lines_code += '{sp}{ln}: {line}\n'.format(
                sp=line_spacing,
                ln=line_num,
                line=each_line)

        cmd_test = 'mkdir -p {dir}/.pylint.d && ' \
                   'export PYTHONPATH=$PYTHONPATH:{dir} && ' \
                   'export PYLINTHOME={dir}/.pylint.d && ' \
                   '{py} -m pylint -d I,W0621,C0103,C0111,C0301,C0327,C0410,C0413,R0201,R0903,W0201,W0612 {path}'.format(
                    dir=INSTALL_DIRECTORY, py=sys.executable, path=file_run)
        cmd_out, _, cmd_status = cmd_output(cmd_test, user='root')

        message = Markup(
            '<pre>\n\n'
            'Full Python Code Input code:\n\n{code}\n\n'
            'Python Code Input code analysis:\n\n{report}'
            '</pre>'.format(
                code=lines_code.replace("<", "&lt"), report=cmd_out.decode("utf-8")))
    except Exception as err:
        cmd_status = None
        message = "Error running pylint: {}".format(err)
        error.append(message)

    if cmd_status:
        warning.append("pylint returned with status: {}".format(cmd_status))

    if message:
        info.append(
            "Review your code for issues and test before putting it "
            "into a production environment.")
        info.append(message)

    return info, warning, success, error
