#!/bin/sh
# Docker entrypoint — regenerates widget_template_*.html once, right before
# the real service command starts, then hands off.
#
# user_templates/widget_template_*.html (aot/aot_flask/templates/) is a
# generated artifact derived from each widget's widget_dashboard_head/body
# (aot/widgets/*.py) -- excluded from both git and the Docker build context
# (.gitignore/.dockerignore), so it is never baked into the image. It used
# to only regenerate on an explicit widget install/import/settings-regenerate
# action. A bare-metal install never notices: the directory persists on disk
# across restarts. But a Docker image swap starts every container from that
# image's fresh, empty user_templates/ -- nothing had ever filled it in,
# so every dashboard widget rendered with no UI after an update
# (2026-08-15 user report).
#
# This runs once per container start (not per app-process start -- a
# gunicorn worker respawn inside an already-running container does NOT
# re-run this entrypoint). That is deliberate: an earlier attempt hooked
# the same regeneration into create_app() instead, which fired on every
# worker restart too, not only when a container is actually (re)created
# after an upgrade (2026-08-16 user correction).
set -e

python3 -c "
try:
    from aot.utils.widget_generate_html import generate_widget_html
    errors = generate_widget_html()
    if errors:
        print(f'[entrypoint] generate_widget_html() reported {len(errors)} error(s): {errors}', flush=True)
    else:
        print('[entrypoint] Regenerated widget_template_*.html.', flush=True)
except Exception as e:
    # A broken custom widget must not take the whole stack down with it --
    # log and keep booting rather than let this abort the container.
    print(f'[entrypoint] generate_widget_html() failed: {e}', flush=True)
"

exec "$@"
