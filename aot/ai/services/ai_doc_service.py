# coding=utf-8
# @ANCHOR: AI_DOC_SERVICE
"""
AiDocService — single access point for AI to query docs/ai_docs/*.json documentation.

Design ref: 031_FUNCTION_CENTRIC_DESIGN_PROPOSAL.yaml (Section 4)
Law 1: New service file only — no modification to existing docs/ai_docs files.
Law 2: @ANCHOR: AI_DOC_SERVICE registered via incremental_update.py.

Data sources (relative to project root, no absolute paths):
  docs/ai_docs/functions.json  — function catalogue
  docs/ai_docs/outputs.json    — output device catalogue
  docs/ai_docs/inputs.json     — input measurement catalogue
  docs/ai_docs/ai_doc_index.json — markdown documentation index
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Entry dataclasses ─────────────────────────────────────────────────────────

@dataclass
class FunctionDocEntry:
    name: str
    function_name: str = ""
    description: str = ""
    input_types: List[str] = field(default_factory=list)
    output_types: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    example_usage: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputDocEntry:
    output_type: str
    output_name: str = ""
    interfaces: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InputDocEntry:
    input_type: str
    input_name: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# ── Service ───────────────────────────────────────────────────────────────────

class AiDocService:
    """
    Loads docs/ai_docs/*.json at first access and caches in class-level dict.
    All lookups are case-insensitive on the key.
    Thread-safety: read-heavy, written only at startup — no lock needed for CPython GIL.

    @phase active
    @stability stable
    """

    _functions:  Optional[Dict[str, Any]] = None
    _outputs:    Optional[Dict[str, Any]] = None
    _inputs:     Optional[Dict[str, Any]] = None
    _index:      Optional[Dict[str, Any]] = None
    _ai_docs_path: Optional[str] = None

    # ── Initialisation ────────────────────────────────────────────────────────

    @classmethod
    def _resolve_docs_path(cls) -> str:
        """
        Locate docs/ai_docs relative to this file's position in the source tree.
        No absolute paths (Law hardcoding_prohibition).
        """
        if cls._ai_docs_path:
            return cls._ai_docs_path
        # this file: aot/services/ai_doc_service.py
        # docs/ai_docs: ../../docs/ai_docs relative to this file
        here = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.normpath(os.path.join(here, "..", "..", "docs", "ai_docs"))
        if os.path.isdir(candidate):
            cls._ai_docs_path = candidate
            return candidate
        # Fallback: try Flask app root from environment
        root = os.environ.get("MYCODO_PATH") or os.environ.get("APP_ROOT", "")
        fallback = os.path.join(root, "docs", "ai_docs")
        cls._ai_docs_path = fallback
        return fallback

    @classmethod
    def _load_json(cls, filename: str) -> Dict[str, Any]:
        path = os.path.join(cls._resolve_docs_path(), filename)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            logger.warning("[AiDocService] File not found: %s", path)
            return {}
        except json.JSONDecodeError as exc:
            logger.error("[AiDocService] JSON parse error in %s: %s", path, exc)
            return {}

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._functions is None:
            cls._functions = cls._load_json("functions.json")
        if cls._outputs is None:
            cls._outputs = cls._load_json("outputs.json")
        if cls._inputs is None:
            cls._inputs = cls._load_json("inputs.json")
        if cls._index is None:
            cls._index = cls._load_json("ai_doc_index.json")

    @classmethod
    def invalidate_cache(cls) -> None:
        """Force reload on next access (call after docs/ai_docs update)."""
        cls._functions = None
        cls._outputs = None
        cls._inputs = None
        cls._index = None
        logger.info("[AiDocService] Cache invalidated.")

    # ── Lookup methods ────────────────────────────────────────────────────────

    @classmethod
    def get_function_doc(cls, name: str) -> Optional[FunctionDocEntry]:
        """Return FunctionDocEntry for name, or None if not found."""
        cls._ensure_loaded()
        raw = cls._functions.get(name) or cls._functions.get(name.lower())
        if raw is None:
            return None
        return FunctionDocEntry(
            name=name,
            function_name=raw.get("function_name", ""),
            description=raw.get("description", ""),
            input_types=raw.get("input_types", []),
            output_types=raw.get("output_types", []),
            constraints=raw.get("constraints", []),
            example_usage=raw.get("example_usage", ""),
            raw=raw,
        )

    @classmethod
    def get_output_doc(cls, output_type: str) -> Optional[OutputDocEntry]:
        """Return OutputDocEntry for output_type, or None if not found."""
        cls._ensure_loaded()
        raw = cls._outputs.get(output_type) or cls._outputs.get(output_type.lower())
        if raw is None:
            return None
        return OutputDocEntry(
            output_type=output_type,
            output_name=raw.get("output_name", ""),
            interfaces=raw.get("interfaces", []),
            raw=raw,
        )

    @classmethod
    def get_input_doc(cls, input_type: str) -> Optional[InputDocEntry]:
        """Return InputDocEntry for input_type, or None if not found."""
        cls._ensure_loaded()
        raw = cls._inputs.get(input_type) or cls._inputs.get(input_type.lower())
        if raw is None:
            return None
        return InputDocEntry(
            input_type=input_type,
            input_name=raw.get("input_name", raw.get("name", "")),
            raw=raw,
        )

    @classmethod
    def get_device_constraints(cls, output_id: str) -> List[str]:
        """Return constraint strings for output_id from outputs.json, empty list if absent."""
        doc = cls.get_output_doc(output_id)
        if doc is None:
            return []
        return doc.raw.get("constraints", [])

    # ── Search ────────────────────────────────────────────────────────────────

    @classmethod
    def search(cls, query: str, doc_type: str = "functions") -> List[Dict[str, Any]]:
        """
        Keyword search across the specified doc_type catalogue.

        doc_type: "functions" | "outputs" | "inputs"
        Returns a list of dicts (raw entries) ranked by match count, best-first.
        Caller should slice [:3] for top-3 injection into ReasoningContext.
        """
        cls._ensure_loaded()

        catalogue: Dict[str, Any] = {
            "functions": cls._functions,
            "outputs":   cls._outputs,
            "inputs":    cls._inputs,
        }.get(doc_type, cls._functions) or {}

        q_lower = query.lower()
        q_tokens = set(q_lower.split())

        scored: List[tuple] = []
        for key, value in catalogue.items():
            if not isinstance(value, dict):
                continue
            haystack = (
                key.lower() + " " +
                value.get("function_name", value.get("output_name", value.get("input_name", ""))).lower() + " " +
                value.get("description", "").lower()
            )
            score = sum(1 for token in q_tokens if token in haystack)
            if score > 0:
                scored.append((score, key, value))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"key": k, **v} for _, k, v in scored]

    # @ANCHOR: WEATHER_DEVICE_CLASSIFY_DOC  [2026-03-24 — 001_WEATHER_LOGIC_UPGRADE patch_2]
    _WEATHER_CLASSIFY_KEYWORDS = frozenset([
        'weather', '날씨', '기상', '기온', '강수', '풍속',
        '온도', '습도', '기압', '대기', 'temperature', 'humidity',
        'pressure', 'wind', 'rain', 'climate', 'atmospheric',
    ])

    @classmethod
    def classify_weather_device(cls, device_name: str, notes: str = '') -> bool:
        """
        Return True if device_name or notes contain weather/environmental keywords.
        Used as the semantic gate for WeatherTag classification without a full DB lookup.
        Delegates cache management to DeviceCapabilityRegistry.tag_weather_device().
        """
        combined = (device_name + ' ' + (notes or '')).lower()
        return any(kw in combined for kw in cls._WEATHER_CLASSIFY_KEYWORDS)
