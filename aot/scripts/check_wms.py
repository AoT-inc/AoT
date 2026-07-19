"""Dump AoT_map widget options from the database for inspection."""
from aot.start_flask_ui import app
from aot.databases.models import Widget
import json

with app.app_context():
    widgets = Widget.query.filter_by(graph_type='AoT_map').all()
    for w in widgets:
        opts_str = w.custom_options
        if opts_str:
            try:
                opts = json.loads(opts_str)
                print(f"Widget {w.unique_id}:")
                print(f"  active_layers: {opts.get('active_layers')}")
                print(f"  fallback_center: {opts.get('fallback_center')}")
            except Exception as e:
                print(f"Error parsing json for widget {w.unique_id}: {e}")
