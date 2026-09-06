# -*- coding: utf-8 -*-
"""Shared helper to pin the Babel locale for manual doc generation."""
import os
from contextlib import contextmanager

from flask import Flask
from flask_babel import Babel
from flask_babel import force_locale

# The app's translation catalogs live under aot/aot_flask/translations. Our
# throwaway Flask app below does not live in that package, so Flask-Babel's
# default (translations/ next to the app module) would never find them -
# point it there explicitly, with an absolute path so it works regardless
# of the caller's working directory.
_TRANSLATIONS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "aot_flask", "translations")
)


@contextmanager
def doc_locale(lang):
    """Force lazy_gettext() strings to resolve in a given locale during doc generation.

    These scripts run with no request context, so lazy_gettext() normally
    falls back to the untranslated (English) source string regardless of
    ambient state (e.g. INSTALL_DIRECTORY/.language). Push a throwaway
    app/Babel context pinned to `lang`, pointed at the real translation
    catalogs, so the output is deterministic and reflects that language.

    Any code that reads catalog-backed strings (e.g. parse_input_information())
    must run *inside* this context manager, not just the file-writing step -
    lazy_gettext() strings resolve to plain str the moment they are read
    (interpolated, concatenated, etc.), so parsing done outside a locale
    context - or reused across multiple doc_locale() calls - bakes in
    whichever locale was active when it ran.
    """
    app = Flask(__name__)
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = _TRANSLATIONS_DIR
    Babel(app)
    with app.app_context(), force_locale(lang):
        yield


def english_locale():
    """Backwards-compatible alias for doc_locale('en')."""
    return doc_locale('en')
