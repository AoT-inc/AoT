# coding=utf-8
import logging

logger = logging.getLogger("aot.atlas_scientific")


def constraints_pass_percent(mod_dev, value):
    """
    Check if the user input is acceptable
    :param mod_dev: SQL object with user-saved options
    :param value: float or int
    :return: tuple: (bool, list of strings)
    """
    errors = []
    all_passed = True
    # Ensure value is positive
    try:
        if 100 < value or value < 0:
            all_passed = False
            errors.append("Must be between 0 and 100")
    except TypeError:
        # If value is None or not comparable, skip constraint
        pass
    return all_passed, errors, mod_dev

def constraints_pass_positive_value(mod_dev, value):
    """
    Check if the user input is acceptable
    :param mod_dev: SQL object with user-saved options
    :param value: float or int
    :return: tuple: (bool, list of strings)
    """
    errors = []
    all_passed = True
    # Ensure value is positive
    try:
        if value <= 0:
            all_passed = False
            errors.append("Must be a positive value")
    except TypeError:
        # Value missing/None: do not fail
        pass
    return all_passed, errors, mod_dev

def constraints_pass_positive_or_zero_value(mod_dev, value):
    """
    Check if the user input is acceptable
    :param mod_dev: SQL object with user-saved options
    :param value: float or int
    :return: tuple: (bool, list of strings)
    """
    errors = []
    all_passed = True
    # Ensure value is above 0
    try:
        if value < 0:
            all_passed = False
            errors.append("Must be a positive value")
    except TypeError:
        # Value missing/None: do not fail
        pass
    return all_passed, errors, mod_dev


def constraints_pass_hhmm(mod_dev, value):
    """하루 시각 `HH:MM` 텍스트 옵션 검사 — 못 읽는 값은 저장을 거부한다.

    빈 값은 통과(옵션을 비워 기본값으로 돌리는 것은 정상). 파서의 정본은
    `aot.utils.clock_hhmm.parse_hhmm` 이고, 읽는 쪽도 같은 파서를 쓴다.
    """
    from aot.utils.clock_hhmm import parse_hhmm
    if value is None or str(value).strip() == '':
        return True, [], mod_dev
    if parse_hhmm(value) is None:
        return False, ["Must be a time of day as HH:MM (00:00-24:00)"], mod_dev
    return True, [], mod_dev
