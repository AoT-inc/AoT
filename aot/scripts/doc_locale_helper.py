# -*- coding: utf-8 -*-
"""Shared helper to pin the Babel locale to English for manual doc generation."""
from contextlib import contextmanager

from flask import Flask
from flask_babel import Babel
from flask_babel import force_locale


@contextmanager
def english_locale():
    """Force lazy_gettext() strings to resolve in English during doc generation.

    These scripts run with no request context, so lazy_gettext() normally
    falls back to the untranslated (English) source string. But if an app
    context happens to already be pushed (e.g. run from a Flask shell) and
    INSTALL_DIRECTORY/.language is set to a non-English language, the
    generated docs render in that language instead. Push a throwaway
    app/Babel context pinned to 'en' so the output is deterministic
    regardless of ambient state.
    """
    app = Flask(__name__)
    Babel(app)
    with app.app_context(), force_locale('en'):
        yield
