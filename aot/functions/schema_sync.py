

# coding=utf-8
"""
schema_sync.py — Generic, namespaced config adapter for AoT
-----------------------------------------------------------
Purpose
-------
Provide a **generic** way for any Function/Widget/Admin UI to share and
synchronize settings via the DB, without being tied to a specific feature
(e.g., valves). This module implements a **namespaced** configuration model
stored inside `CustomController.custom_options` and (optionally) inside each
`FunctionChannel.custom_channel_options`, with **per-namespace optimistic
locking** using a `cfg_rev` integer.

Design
------
- SSOT = DB
  * Controller-level (global) config per namespace:
      CustomController.custom_options = {
        "namespaces": {
          "<ns>": { "cfg_rev": <int>, ... namespace-specific keys ... },
          ...
        },
        "cfg_rev": <int>   # (optional) overall rev, not managed here
      }
  * Channel-level config per namespace (optional):
      FunctionChannel.custom_channel_options = {
        "namespaces": {
          "<ns>": { ... namespace-specific keys ... }
        }
      }

- Per-namespace revision:
    - Only the controller-level namespace dict holds `cfg_rev`.
    - Channel-level payloads do NOT carry/require `cfg_rev`.

- This module is intentionally **domain-agnostic**:
    - No assumptions about specific keys (e.g., "window"/"pump"/"valves").
    - No field normalization; callers/feature-adapters can do that on top.

Public API
----------
Controller namespace:
  - read_ns(controller_id, ns) -> dict
  - write_ns(controller_id, ns, payload, expect_rev=None) -> new_rev:int

Channel namespace:
  - read_ns_channels(controller_id, ns) -> list[dict]    # [{"index": 1, ...}, ...]
  - write_ns_channels(controller_id, ns, items:list[dict]) -> None

Combined helpers:
  - get_namespace_schema(controller_id, ns) -> {"cfg_rev": int, "global": dict, "channels": list[dict]}
  - set_namespace_schema(controller_id, ns, global_payload:dict, channels_payload:list[dict] | None, expect_rev:int|None) -> int

Runtime helper:
  - load_namespace(func_obj, controller_id, ns, apply_fn, *, with_channels=True)
    -> schema dict returned by get_namespace_schema()
    where apply_fn: (func_obj, global_dict, channels_list) -> None

Exceptions:
  - ConflictError: raised by write_ns() / set_namespace_schema() when expect_rev mismatch.

Notes
-----
- We purposefully do NOT create or delete FunctionChannel rows here. We only
  update existing rows belonging to the controller, in ascending DB id order.
- If you need field normalization/validation, build a thin feature adapter
  on top of this (e.g., adapters/valve_adapter.py) and call into schema_sync.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Callable

from aot.aot_flask.extensions import db
from aot.databases.models import CustomController, FunctionChannel
from aot.utils.database import db_retrieve_table_daemon


# ---------------------------
# Exceptions
# ---------------------------
class ConflictError(Exception):
  """Raise when cfg_rev optimistic-lock check fails.

  @phase co-growth
  @stability stable
  """
  pass


# ---------------------------
# JSON utilities
# ---------------------------
def _json_loads_safe(txt: Optional[str]) -> Dict[str, Any]:
  if not txt:
    return {}
  try:
    v = json.loads(txt)
    return v if isinstance(v, dict) else {}
  except Exception:
    return {}

def _json_dumps(d: Dict[str, Any]) -> str:
  try:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))
  except Exception:
    return "{}"


# ---------------------------
# Internal helpers
# ---------------------------
def _get_ctrl_options(ctrl: CustomController) -> Dict[str, Any]:
  return _json_loads_safe(getattr(ctrl, "custom_options", None))

def _put_ctrl_options(ctrl: CustomController, root: Dict[str, Any]) -> None:
  ctrl.custom_options = _json_dumps(root)
  db.session.add(ctrl)

def _ensure_ns_dict(root: Dict[str, Any]) -> Dict[str, Any]:
  spaces = root.get("namespaces")
  if not isinstance(spaces, dict):
    spaces = {}
    root["namespaces"] = spaces
  return spaces


# ---------------------------
# Public: Controller namespace
# ---------------------------
def read_ns(controller_id: str, ns: str) -> Dict[str, Any]:
  """Return controller-level namespace payload with ensured cfg_rev integer."""
  ctrl = db_retrieve_table_daemon(CustomController, unique_id=controller_id)
  if not ctrl:
    return {"cfg_rev": 0}
  root = _get_ctrl_options(ctrl)
  spaces = _ensure_ns_dict(root)
  data = spaces.get(ns) or {}
  if not isinstance(data, dict):
    data = {}
  # ensure int
  try:
    data["cfg_rev"] = int(data.get("cfg_rev", 0) or 0)
  except Exception:
    data["cfg_rev"] = 0
  return data


def write_ns(controller_id: str, ns: str, payload: Dict[str, Any], expect_rev: Optional[int] = None) -> int:
  """Persist controller-level namespace dict with optimistic locking.

  Raises ConflictError when expect_rev does not match current cfg_rev.
  Returns the new cfg_rev (current + 1).
  """
  ctrl = db_retrieve_table_daemon(CustomController, unique_id=controller_id)
  if not ctrl:
    raise ValueError("CustomController not found")

  root = _get_ctrl_options(ctrl)
  spaces = _ensure_ns_dict(root)
  cur = spaces.get(ns) or {}
  if not isinstance(cur, dict):
    cur = {}

  try:
    cur_rev = int(cur.get("cfg_rev", 0) or 0)
  except Exception:
    cur_rev = 0

  if expect_rev is not None and int(expect_rev) != cur_rev:
    raise ConflictError(f"cfg_rev mismatch (expect={expect_rev}, actual={cur_rev})")

  new_rev = cur_rev + 1
  payload = dict(payload or {})
  payload["cfg_rev"] = new_rev
  spaces[ns] = payload
  root["namespaces"] = spaces
  _put_ctrl_options(ctrl, root)
  db.session.commit()
  return new_rev


# ---------------------------
# Public: Channel namespace
# ---------------------------
def read_ns_channels(controller_id: str, ns: str) -> List[Dict[str, Any]]:
  """Return per-channel namespace dicts ordered by FunctionChannel.id."""
  q = db_retrieve_table_daemon(FunctionChannel).filter(FunctionChannel.function_id == controller_id)
  rows = q.order_by(FunctionChannel.id.asc()).all()
  out: List[Dict[str, Any]] = []
  for idx, row in enumerate(rows, start=1):
    ch = _json_loads_safe(getattr(row, "custom_channel_options", None))
    spaces = ch.get("namespaces")
    if not isinstance(spaces, dict):
      spaces = {}
    data = spaces.get(ns) or {}
    if not isinstance(data, dict):
      data = {}
    # include stable per-channel index so callers can round-trip easily
    out.append({"index": idx, **data})
  return out


def write_ns_channels(controller_id: str, ns: str, items: List[Dict[str, Any]]) -> None:
  """Persist per-channel namespace dicts without creating or deleting rows."""
  q = db_retrieve_table_daemon(FunctionChannel).filter(FunctionChannel.function_id == controller_id)
  rows = q.order_by(FunctionChannel.id.asc()).all()

  if not isinstance(items, list):
    items = []

  limit = min(len(rows), len(items))
  for i in range(limit):
    row = rows[i]
    src = items[i] if isinstance(items[i], dict) else {}
    # remove "index" if provided
    if "index" in src:
      src = {k: v for k, v in src.items() if k != "index"}

    ch = _json_loads_safe(getattr(row, "custom_channel_options", None))
    spaces = ch.get("namespaces")
    if not isinstance(spaces, dict):
      spaces = {}
    spaces[ns] = src
    ch["namespaces"] = spaces
    row.custom_channel_options = _json_dumps(ch)
    db.session.add(row)

  db.session.commit()


# ---------------------------
# Public: Combined schema I/O
# ---------------------------
def get_namespace_schema(controller_id: str, ns: str) -> Dict[str, Any]:
  """Read combined controller-level and channel-level namespace payloads."""
  glob = read_ns(controller_id, ns)
  chans = read_ns_channels(controller_id, ns)
  # Copy cfg_rev to top-level for easy consumers
  cfg_rev = int(glob.get("cfg_rev", 0) or 0)
  return {"cfg_rev": cfg_rev, "global": glob, "channels": chans}


def set_namespace_schema(
    controller_id: str,
    ns: str,
    global_payload: Dict[str, Any],
    channels_payload: Optional[List[Dict[str, Any]]] = None,
    expect_rev: Optional[int] = None
) -> int:
  """Write controller and channel namespace payloads with optimistic lock."""
  new_rev = write_ns(controller_id, ns, global_payload or {}, expect_rev=expect_rev)
  if channels_payload is not None:
    write_ns_channels(controller_id, ns, channels_payload or [])
  return new_rev


# ---------------------------
# Public: Runtime helper
# ---------------------------
def load_namespace(
    func_obj: Any,
    controller_id: str,
    ns: str,
    apply_fn: Callable[[Any, Dict[str, Any], List[Dict[str, Any]]], None],
    *,
    with_channels: bool = True
) -> Dict[str, Any]:
  """Load namespace from DB and apply settings via caller-provided callback."""
  schema = get_namespace_schema(controller_id, ns)
  glob = dict(schema.get("global") or {})
  chans = list(schema.get("channels") or []) if with_channels else []
  try:
    apply_fn(func_obj, glob, chans)
  except Exception as e:
    try:
      # best-effort logging if function logger exists
      func_obj.logger.error(f"[schema_sync] load_namespace apply_fn error: {e}")
    except Exception:
      pass
  return schema