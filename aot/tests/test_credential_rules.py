# coding=utf-8
"""The account rules have one source (aot.utils.utils); everything shown to
people must be derived from it, never restated."""
import re
from pathlib import Path

from aot.utils import utils

ROOT = Path(__file__).resolve().parents[2]


def test_username_bounds_follow_constants():
    lo, hi = utils.USERNAME_MIN_LENGTH, utils.USERNAME_MAX_LENGTH
    assert utils.test_username('a' * lo)
    assert not utils.test_username('a' * (lo - 1))
    assert utils.test_username('a' * hi)
    assert not utils.test_username('a' * (hi + 1))
    assert not utils.test_username('bad_name')


def test_password_bounds_follow_constants():
    n = utils.PASSWORD_MIN_LENGTH
    assert utils.test_password('x9Zq' * (n // 4 + 1))
    assert not utils.test_password('x' * (n - 1))
    assert not utils.test_password('password123')


def test_no_second_copy_of_the_numbers_in_ui_code():
    stale = re.compile(r'at least [0-9]+ characters|between [0-9]+ and [0-9]+ characters'
                       r'|Length\(\s*min=[0-9]')
    for rel in ('aot/aot_flask/routes_authentication.py',
                'aot/aot_flask/routes_password_reset.py',
                'aot/aot_flask/forms/forms_settings.py',
                'aot/aot_flask/utils/utils_settings.py'):
        text = (ROOT / rel).read_text(encoding='utf-8')
        assert not stale.search(text), rel
