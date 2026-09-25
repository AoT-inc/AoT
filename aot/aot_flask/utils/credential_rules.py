# coding=utf-8
"""User-facing wording for the username and password rules.

The rules themselves live in ``aot.utils.utils`` (``USERNAME_MIN_LENGTH`` and
friends). Every hint and error shown to people is built here from those
constants, so the wording can never disagree with what is actually enforced.
"""
from flask_babel import lazy_gettext

from aot.utils.utils import (PASSWORD_MIN_LENGTH, USERNAME_MAX_LENGTH,
                             USERNAME_MIN_LENGTH)


def rules_hint():
    """One-line hint shown next to the account creation form."""
    return lazy_gettext(
        'Usernames must be %(min)d to %(max)d characters and contain only '
        'letters and numbers. Passwords must be at least %(pw_min)d '
        'characters and must not be a commonly used password.',
        min=USERNAME_MIN_LENGTH, max=USERNAME_MAX_LENGTH,
        pw_min=PASSWORD_MIN_LENGTH)


def invalid_username():
    return lazy_gettext(
        'Invalid username. Must be between %(min)d and %(max)d characters '
        'and only contain letters and numbers.',
        min=USERNAME_MIN_LENGTH, max=USERNAME_MAX_LENGTH)


def invalid_password():
    return lazy_gettext(
        'Invalid password. Must be at least %(min)d characters and not be a '
        'commonly used password.',
        min=PASSWORD_MIN_LENGTH)


def password_too_short():
    return lazy_gettext(
        'Password must be at least %(min)d characters.',
        min=PASSWORD_MIN_LENGTH)
