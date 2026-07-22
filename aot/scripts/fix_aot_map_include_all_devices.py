"""One-off repair script for the AoT_map "0 devices shown" bug.

Background: aot/widgets/AoT_map.py execute_at_modification() used to store
include_all_devices=False whenever a user saved the map widget settings
without selecting any device in device_selection_input/output/function.
That combination (include_all_devices=False + empty device_ids) makes
utils_geo.collect_devices() return [] unconditionally, so the map renders
with zero devices even though the user never intended to filter anything.

The write path has already been fixed (unselected -> include_all_devices=True).
This script repairs widgets that were saved under the old buggy logic.

Only widgets matching ALL of these are touched:
  - graph_type == 'AoT_map'
  - custom_options.include_all_devices is False (bool or 'false'/'False' string)
  - custom_options.device_ids is empty/missing
  - device_selection_input/output/function are all empty/missing

Widgets with a non-empty device_ids or any device_selection_* value are a
deliberate user filter and are never modified.

Usage:
    python3 -m aot.scripts.fix_aot_map_include_all_devices           # dry-run (default)
    python3 -m aot.scripts.fix_aot_map_include_all_devices --apply   # write changes

@phase migration
@stability stable
"""
import argparse
import json

from aot.start_flask_ui import app
from aot.databases.models import Widget
from aot.aot_flask.extensions import db


DEVICE_SELECTION_KEYS = (
    'device_selection_input',
    'device_selection_output',
    'device_selection_function',
)


def _is_false(value):
    return value is False or value in ('false', 'False')


def _is_empty(value):
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    if isinstance(value, str):
        return value.strip() in ('', '[]')
    return False


def find_affected_widgets():
    """Return list of (Widget, options_dict) matching the bug pattern."""
    affected = []
    widgets = Widget.query.filter_by(graph_type='AoT_map').all()
    for widget in widgets:
        raw = widget.custom_options
        if not raw:
            continue
        try:
            options = json.loads(raw)
        except (TypeError, ValueError):
            print(f"  [skip] widget {widget.unique_id} ({widget.name!r}): "
                  f"custom_options is not valid JSON, leaving untouched")
            continue
        if not isinstance(options, dict):
            continue

        if not _is_false(options.get('include_all_devices')):
            continue
        if not _is_empty(options.get('device_ids')):
            continue
        if any(not _is_empty(options.get(key)) for key in DEVICE_SELECTION_KEYS):
            continue

        affected.append((widget, options))
    return affected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply', action='store_true',
        help="Actually write the fix. Without this flag, only lists affected widgets.")
    args = parser.parse_args()

    with app.app_context():
        affected = find_affected_widgets()

        if not affected:
            print("영향받는 AoT_map 위젯이 없습니다.")
            return

        print(f"{len(affected)}개의 AoT_map 위젯이 include_all_devices=False + "
              f"device_ids=[] 버그 패턴에 해당합니다:\n")
        for widget, options in affected:
            print(f"  - widget id={widget.id} unique_id={widget.unique_id} "
                  f"name={widget.name!r} tab_id={widget.tab_id}")

        if not args.apply:
            print("\n(dry-run) 아무것도 변경하지 않았습니다. 실제 적용하려면 --apply 를 추가하세요.")
            return

        print()
        for widget, options in affected:
            options['include_all_devices'] = True
            widget.custom_options = json.dumps(options)
            db.session.add(widget)
            print(f"  [fixed] widget id={widget.id} unique_id={widget.unique_id} "
                  f"name={widget.name!r}")
        db.session.commit()
        print(f"\n{len(affected)}개 위젯의 include_all_devices 를 True 로 수정하고 커밋했습니다.")


if __name__ == "__main__":
    main()
