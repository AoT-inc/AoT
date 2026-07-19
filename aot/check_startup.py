import sys
import os
# Add AoT/ directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))

# =============================================================
# @ANCHOR: CM_1_SCHEMA_VALIDATION (TASK_17 CM_1 — Hard Migration Protocol)
# Validates that all Column definitions for CRITICAL_MODELS exist in the actual DB.
# If any column is missing, logs [SCHEMA_MISMATCH] and aborts startup.
# NOTE: last_seen is intentionally in-memory (_last_seen dict in MCPBridgeService),
#       NOT a DB column — do NOT add it to CRITICAL_MODELS.
# =============================================================
CRITICAL_MODELS = [
    # (table_name, [required_column_names])
    ("mcp_server",       ["unique_id", "name", "command", "is_activated", "scope"]),
    ("ai_agent",         ["unique_id", "name", "role", "is_activated", "tool_access"]),
    ("agent_mcp_access", ["agent_unique_id", "mcp_unique_id"]),
    ("output",           ["unique_id", "name", "output_type", "is_ai_enabled"]),
    ("output_channel",   ["output_id", "channel"]),
]

def _validate_schema():
    """
    Checks that all CRITICAL_MODELS columns exist in the DB via PRAGMA table_info().
    Returns list of (table, missing_columns) tuples. Empty list = all OK.
    """
    import sqlite3
    from aot.config import DATABASE_PATH
    mismatches = []
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        for table_name, required_cols in CRITICAL_MODELS:
            cursor.execute(f"PRAGMA table_info({table_name})")
            rows = cursor.fetchall()
            existing_cols = {row[1] for row in rows}  # row[1] = column name
            missing = [c for c in required_cols if c not in existing_cols]
            if missing:
                mismatches.append((table_name, missing))
        conn.close()
    except Exception as e:
        print(f"[SCHEMA_MISMATCH] Could not connect to DB for schema validation: {e}")
        mismatches.append(("DB_CONNECTION", [str(e)]))
    return mismatches

_schema_errors = _validate_schema()
if _schema_errors:
    for table, cols in _schema_errors:
        print(f"[SCHEMA_MISMATCH] Table '{table}' is missing columns: {cols}")
    print("[SCHEMA_MISMATCH] Startup aborted. Run Alembic migrations before starting.")
    sys.exit(1)
else:
    print("[SCHEMA_VALIDATION] All critical model columns verified OK.")
# =============================================================
# END CM_1_SCHEMA_VALIDATION
# =============================================================


try:
    from aot.aot_flask.app import create_app
    print("Attempting to create app...")
    app = create_app()
    print("App created successfully.")
    
    client = app.test_client()
    
    print("Testing / route...")
    response = client.get('/', follow_redirects=True)
    print(f"/ status code: {response.status_code}")
    if response.status_code == 200:
        print("/ page access successful")
    else:
        print(f"/ page access failed with status {response.status_code}")
        
    print("Testing /login route...")
    response = client.get('/login', follow_redirects=True)
    print(f"/login status code: {response.status_code}")
    # It might redirect to /login_password
    if response.status_code == 200:
        print("Login page access successful")
        if b"Login" in response.data or b"login" in response.data:
             print("Login text found")
    else:
        print(f"Login page access failed with status {response.status_code}")

    print("Testing /map route (should redirect to login)...")
    response_map = client.get('/map', follow_redirects=False)
    print(f"/map status code: {response_map.status_code}")
    if response_map.status_code == 302:
        print(f"/map redirected to: {response_map.headers['Location']}")
    else:
        print(f"/map returned status {response_map.status_code}")

except Exception as e:
    print(f"Failed to create app or run tests: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
