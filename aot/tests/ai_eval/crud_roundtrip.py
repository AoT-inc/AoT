# coding=utf-8
"""
CRUD round-trip regression harness — AI v3 evaluation, Phase 0a.

Verifies the AI entity-CRUD tools (the deterministic mutation handlers on
AoTDataToolService) actually create → modify → delete the real DB rows and
clean up after themselves. This is the "최종 DB 상태를 assert" half of the
golden-set plan that the prompt-based runner.py cannot cover on a
credential-less DB snapshot: it drives the tool HANDLERS directly, so it needs
NO LLM/API credentials and costs no tokens — it exercises the exact DB
mutation path the AI proposes, minus the model round-trip.

SCOPE — only the ORM-pure handlers run by default:
  * AI Agent   : create_ai_agent → modify_ai_agent → delete_ai_agent
  * device loc : set_device_location (moves a real device, then RESTORES its
                 original lat/lng — a true round-trip, net-zero DB change)
Both are plain SQLAlchemy on the AIAgent / Input|Output models with no daemon
or measurement-DB side effects, so they are safe against a copied dev DB.

Input/Output CRUD is DELIBERATELY GATED OFF by default (--include-daemon-crud):
create_output/delete_output go through output_add/output_del + DaemonControl
(the FakeForm-over-web-util pattern), and the running daemon operates on the
LIVE database, not this copy — so executing them can reach past the copy and
touch live daemon/measurement state (see the 라이브 DB 테스트 금지 incident in
memory). Only enable that flag in a fully isolated, daemon-less environment.

SAFETY: like runner.py, this makes REAL writes to the DB at db_path, so
db_path MUST be a COPY (sqlite .backup(), not cp — WAL), never the live one.
Every created row is removed in a finally block even if an assertion fails.

Usage (manual, not pytest-collected):
    python -m aot.tests.ai_eval.crud_roundtrip --db-path /path/to/copy/of/aot.db \\
        [--include-daemon-crud]
"""
import argparse
import json
import os
from datetime import datetime

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    '.local', 'reports',
)
CRUD_LOG_PATH = os.path.join(REPORTS_DIR, 'ai_v3_crud_roundtrip.md')

# Marker prefix on every row this harness creates, so a leaked row (if cleanup
# ever fails) is greppable and obviously synthetic — never a real user entity.
_MARK = 'golden_crud_probe'


def _step(results, name, ok, detail=''):
    results.append({'step': name, 'ok': bool(ok), 'detail': detail})
    return ok


def _ai_agent_roundtrip(results):
    """create → modify → delete an AIAgent, asserting DB state at each hop.
    Pure ORM (AIAgent + AgentMCPAccess); no daemon/measurement side effects."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.databases.models.ai import AIAgent, AIEntry

    entry = AIEntry.query.first()
    if not entry:
        _step(results, 'ai_agent:precheck', False, 'no AIEntry in DB to bind an agent to')
        return
    _step(results, 'ai_agent:precheck', True, f'binding to entry {entry.unique_id}')

    created_id = None
    try:
        name = f'{_MARK}_agent'
        res = AoTDataToolService.create_ai_agent(name=name, entry_id=entry.unique_id)
        created_id = res.get('agent_id')
        _step(results, 'ai_agent:create',
              res.get('status') == 'created' and bool(created_id),
              f'result={res}')
        if not created_id:
            return
        in_db = AIAgent.query.filter_by(unique_id=created_id).first()
        _step(results, 'ai_agent:create_in_db',
              in_db is not None and in_db.name == name,
              f'name={getattr(in_db, "name", None)!r}')

        new_name = f'{_MARK}_agent_renamed'
        mres = AoTDataToolService.modify_ai_agent(agent_id=created_id, name=new_name,
                                                  specialty='golden-probe')
        reloaded = AIAgent.query.filter_by(unique_id=created_id).first()
        _step(results, 'ai_agent:modify',
              mres.get('status') == 'modified' and reloaded is not None
              and reloaded.name == new_name,
              f'changed={mres.get("changed")}, name_now={getattr(reloaded, "name", None)!r}')
    finally:
        if created_id:
            dres = AoTDataToolService.delete_ai_agent(agent_id=created_id)
            gone = AIAgent.query.filter_by(unique_id=created_id).first() is None
            _step(results, 'ai_agent:delete',
                  dres.get('status') == 'deleted' and gone,
                  f'result={dres}, gone={gone}')


def _device_location_roundtrip(results):
    """set_device_location on a real device, then RESTORE its original coords —
    net-zero. Pure ORM write to the latitude/longitude columns."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.databases.models import Input, Output

    target = (Output.query.filter(Output.unique_id.isnot(None)).first()
              or Input.query.filter(Input.unique_id.isnot(None)).first())
    if not target:
        _step(results, 'device_loc:precheck', False, 'no Input/Output device in DB')
        return
    dev_id = target.unique_id
    orig_lat = getattr(target, 'latitude', None)
    orig_lng = getattr(target, 'longitude', None)
    _step(results, 'device_loc:precheck', True,
          f'device={dev_id}, orig=({orig_lat},{orig_lng})')

    restored = False
    try:
        probe_lat, probe_lng = 37.123456, 127.654321
        res = AoTDataToolService.set_device_location(device_id=dev_id, lat=probe_lat, lng=probe_lng)
        moved = (Output.query.filter_by(unique_id=dev_id).first()
                 or Input.query.filter_by(unique_id=dev_id).first())
        _step(results, 'device_loc:set',
              res.get('status') == 'placed'
              and abs((moved.latitude or 0) - probe_lat) < 1e-6
              and abs((moved.longitude or 0) - probe_lng) < 1e-6,
              f'result={res}, now=({moved.latitude},{moved.longitude})')
    finally:
        # Restore ORIGINAL coords. If the device had no coords before, write
        # them back as NULL directly (set_device_location requires non-null).
        if orig_lat in (None, '') or orig_lng in (None, ''):
            from aot.databases.models import db as _db
            obj = (Output.query.filter_by(unique_id=dev_id).first()
                   or Input.query.filter_by(unique_id=dev_id).first())
            if obj is not None:
                obj.latitude = orig_lat
                obj.longitude = orig_lng
                _db.session.commit()
                restored = True
        else:
            AoTDataToolService.set_device_location(device_id=dev_id, lat=orig_lat, lng=orig_lng)
            restored = True
        check = (Output.query.filter_by(unique_id=dev_id).first()
                 or Input.query.filter_by(unique_id=dev_id).first())

        def _eq(a, b):
            if a in (None, '') and b in (None, ''):
                return True
            try:
                return abs(float(a) - float(b)) < 1e-6
            except (TypeError, ValueError):
                return a == b
        _step(results, 'device_loc:restore',
              restored and _eq(getattr(check, 'latitude', None), orig_lat)
              and _eq(getattr(check, 'longitude', None), orig_lng),
              f'restored to ({getattr(check, "latitude", None)},{getattr(check, "longitude", None)})')


def _output_crud_roundtrip(results):
    """create_output → modify_output → delete_output. GATED: goes through
    output_add/output_del + DaemonControl, which can reach the LIVE daemon.
    Only run under --include-daemon-crud in an isolated, daemon-less env."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.databases.models import Output

    types = None
    try:
        types = AoTDataToolService._output_types()
    except Exception as e:
        _step(results, 'output:precheck', False, f'could not load output types: {e}')
        return
    otype = next(iter(sorted(types.keys()))) if types else None
    if not otype:
        _step(results, 'output:precheck', False, 'no registered output types')
        return
    _step(results, 'output:precheck', True, f'using output_type={otype}')

    created_id = None
    try:
        res = AoTDataToolService.create_output(output_type=otype, name=f'{_MARK}_output')
        created_id = res.get('output_id')
        _step(results, 'output:create',
              res.get('status') == 'created' and bool(created_id), f'result={res}')
        if not created_id:
            return
        mres = AoTDataToolService.modify_output(output_id=created_id, name=f'{_MARK}_output_renamed')
        reloaded = Output.query.filter_by(unique_id=created_id).first()
        _step(results, 'output:modify',
              mres.get('status') == 'modified'
              and getattr(reloaded, 'name', None) == f'{_MARK}_output_renamed',
              f'changed={mres.get("changed")}')
    finally:
        if created_id:
            dres = AoTDataToolService.delete_output(output_id=created_id)
            gone = Output.query.filter_by(unique_id=created_id).first() is None
            _step(results, 'output:delete',
                  dres.get('status') == 'deleted' and gone, f'result={dres}, gone={gone}')


def run_crud_roundtrips(db_path, include_daemon_crud=False, label=None):
    """Run the CRUD round-trips against a COPIED database at db_path.

    Refuses without an explicit db_path — never falls back to a live path.
    """
    if not db_path:
        raise ValueError(
            "db_path is required — point this at a COPY of the database, "
            "never the live one (see project rule: 라이브 DB 테스트 금지)."
        )
    if not os.path.isfile(db_path):
        raise ValueError(f"db_path does not exist: {db_path}")

    # Keep ALEMBIC_RUNNING=1 so create_app SKIPS its startup migration: that
    # path (alembic_upgrade_db) shells out to upgrade_commands.sh, which reads
    # alembic.ini / AOT_PATH and would upgrade the LIVE dev DB — never the copy.
    #
    # PRECONDITION: db_path must already be at the current schema. When the live
    # dev DB lags the code's migration head (observed: live at p5_25, code at
    # p5_38, models referencing ai_entry.protocol that the snapshot lacks), a
    # raw .backup() copy is stale and the handlers will raise "no such column".
    # Migrate the COPY first — safely, without touching live — by redirecting
    # the whole app+alembic chain at a sandbox via AOT_LOCAL_DIR and running
    # `alembic upgrade head` in-process against it (asserting the resolved URI
    # is the sandbox before writing). This harness does NOT migrate; it assumes
    # a current-schema copy so it can never be the thing that reaches live.
    os.environ["ALEMBIC_RUNNING"] = "1"
    from aot.aot_flask.app import create_app
    from aot.config import ProdConfig

    class _EvalConfig(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
        TESTING = True

    app = create_app(config=_EvalConfig)
    results = []
    with app.app_context():
        _ai_agent_roundtrip(results)
        _device_location_roundtrip(results)
        if include_daemon_crud:
            _output_crud_roundtrip(results)
        else:
            _step(results, 'output:skipped', True,
                  'gated off — pass --include-daemon-crud in an isolated daemon-less env')

    _write_results(results, label=label)
    return results


def _write_results(results, label=None):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    passed = sum(1 for r in results if r['ok'])
    failed = len(results) - passed
    with open(CRUD_LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(f"\n## CRUD round-trip {datetime.utcnow().isoformat()}Z"
                + (f" — {label}" if label else "") + "\n\n")
        f.write(f"- steps: {len(results)} · passed: {passed} · failed: {failed}\n")
        for r in results:
            mark = 'PASS' if r['ok'] else 'FAIL'
            f.write(f"  - [{mark}] {r['step']}: {r['detail']}\n")


def _summarize(results):
    passed = sum(1 for r in results if r['ok'])
    return {'steps': len(results), 'passed': passed, 'failed': len(results) - passed,
            'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db-path', required=True, help='Path to a COPY of the database (never the live one)')
    parser.add_argument('--include-daemon-crud', action='store_true',
                        help='Also run Output CRUD (output_add/DaemonControl) — ISOLATED envs only')
    parser.add_argument('--label', default=None)
    args = parser.parse_args()

    out = run_crud_roundtrips(db_path=args.db_path,
                              include_daemon_crud=args.include_daemon_crud, label=args.label)
    print(json.dumps(_summarize(out), ensure_ascii=False, indent=2))
