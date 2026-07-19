#!/bin/bash
# =============================================================================
# AoT Docker Check & Start Script
# Generated: 2026-03-26
# Purpose: Check Docker status, verify migration, start services
# =============================================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo " AoT Docker Environment Check & Start"
echo "=========================================="
echo ""

# -----------------------------------------------
# Step 1: Check Docker daemon
# -----------------------------------------------
echo "[Step 1] Checking Docker daemon..."
if ! docker info > /dev/null 2>&1; then
    echo "  ERROR: Docker is not running. Please start Docker Desktop first."
    exit 1
fi
echo "  Docker daemon: OK"
echo ""

# -----------------------------------------------
# Step 2: Check existing containers
# -----------------------------------------------
echo "[Step 2] Checking existing AoT containers..."
cd "$SCRIPT_DIR"
docker-compose ps 2>/dev/null || docker compose ps 2>/dev/null
echo ""

# -----------------------------------------------
# Step 3: Verify Alembic HEAD
# -----------------------------------------------
echo "[Step 3] Verifying Alembic migration HEAD..."
cd "$PROJECT_DIR/alembic_db"
ALEMBIC_HEAD=$(alembic current 2>&1 | grep -E '^[a-f0-9]+ \(head\)' || true)
echo "  Current HEAD: $ALEMBIC_HEAD"
if echo "$ALEMBIC_HEAD" | grep -q "36b52ba0"; then
    echo "  Migration status: OK (36b52ba0 applied)"
else
    echo "  WARNING: Expected 36b52ba0 as HEAD"
fi
echo ""

# -----------------------------------------------
# Step 4: Verify DB tables
# -----------------------------------------------
echo "[Step 4] Verifying database tables..."
cd "$PROJECT_DIR"
python3 -c "
import sys, os
sys.path.insert(0, '.')
os.environ['ALEMBIC_RUNNING'] = '1'
from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
app = create_app()
with app.app_context():
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    required = ['ai_context_record', 'ai_facility_learning', 'ai_feedback_event', 'ai_onboarding_record']
    all_ok = True
    for t in required:
        status = 'PRESENT' if t in tables else 'MISSING'
        if status == 'MISSING': all_ok = False
        print(f'  {t}: {status}')
    notes_cols = [c['name'] for c in inspector.get_columns('notes')]
    cs = 'PRESENT' if 'context_state' in notes_cols else 'MISSING'
    if cs == 'MISSING': all_ok = False
    print(f'  notes.context_state: {cs}')
    if all_ok:
        print('  DB schema: ALL OK')
    else:
        print('  DB schema: INCOMPLETE — check missing items above')
" 2>&1 | grep -E '(PRESENT|MISSING|ALL OK|INCOMPLETE)'
echo ""

# -----------------------------------------------
# Step 5: Start Docker services
# -----------------------------------------------
echo "[Step 5] Starting Docker services..."
cd "$SCRIPT_DIR"

# Stop existing containers if running
echo "  Stopping existing containers..."
docker-compose down 2>/dev/null || docker compose down 2>/dev/null || true

echo "  Building and starting containers..."
docker-compose up -d --build 2>/dev/null || docker compose up -d --build 2>/dev/null

echo ""
echo "  Waiting for services to start (10 seconds)..."
sleep 10

# -----------------------------------------------
# Step 6: Health check
# -----------------------------------------------
echo "[Step 6] Health check..."
echo "  Checking aot-app container..."
docker-compose ps 2>/dev/null || docker compose ps 2>/dev/null

echo ""
echo "  Testing Flask app response..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8084/ 2>/dev/null || echo "FAIL")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
    echo "  Flask app: RUNNING (HTTP $HTTP_CODE)"
else
    echo "  Flask app: NOT RESPONDING (HTTP $HTTP_CODE)"
    echo "  Check logs: docker-compose logs aot-app"
fi

echo ""
echo "=========================================="
echo " Done. Server should be running at:"
echo "   http://localhost:8084"
echo "=========================================="
