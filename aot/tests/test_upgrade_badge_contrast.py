# coding=utf-8
"""Regression guard for the nav-bar "Upgrade" badge contrast bug.

Background: routes_static.upgrade_badge_is_light() (formerly inline in
inject_variables()) read a dropped legacy JSON key (bg_upgrade, folded into
badge_upgrade in the 2026-07 field consolidation) and referenced a
SettingsCustomUI attribute that no longer exists (SettingsCustomUI().bg_upgrade).
Both misses were swallowed by a bare `except Exception: return True`, so the
badge always rendered as "light" no matter what badge_upgrade was actually
set to -- with the stock dark badge_upgrade (#13261B) and the default
text-color-primary being that same #13261B, the label was invisible
(2026-08-13 user report).
"""
import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)
os.environ.setdefault("ALEMBIC_RUNNING", "1")

from aot.aot_flask.routes_static import upgrade_badge_is_light


def test_settings_custom_ui_has_no_dead_bg_upgrade_attribute():
    """The exact attribute the old code referenced (SettingsCustomUI().bg_upgrade)
    must not silently reappear. Checked at the class level -- instantiating a
    FlaskForm needs a request/session context this test does not set up."""
    from aot.aot_flask.forms.forms_settings import SettingsCustomUI
    assert not hasattr(SettingsCustomUI, 'bg_upgrade')
    assert hasattr(SettingsCustomUI, 'badge_upgrade')


def test_dark_default_badge_is_detected_as_dark():
    # The stock default -- must NOT fall through to the "light" fallback.
    assert upgrade_badge_is_light({}) is False


def test_reads_the_current_field_name():
    assert upgrade_badge_is_light({'badge_upgrade': '#FFFFFF'}) is True
    assert upgrade_badge_is_light({'badge_upgrade': '#000000'}) is False


def test_migrates_the_legacy_key_before_reading(caplog):
    """A theme saved before the 2026-07 consolidation may still carry the old
    key on disk until the next save migrates it -- this must not silently
    ignore that stored value."""
    assert upgrade_badge_is_light({'bg_upgrade': '#FFFFFF'}) is True
    assert upgrade_badge_is_light({'bg_upgrade': '#000000'}) is False


def test_survives_unparseable_color():
    # is_hex_color_light() itself refuses to guess -- that failure must not
    # propagate and break the page.
    assert upgrade_badge_is_light({'badge_upgrade': 'not-a-color'}) is True


def test_none_theme_falls_back_to_the_dark_default():
    # No custom_theme_json yet (fresh install) is not an error case -- it
    # just means the stock default applies, same as an empty dict.
    assert upgrade_badge_is_light(None) is False


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
