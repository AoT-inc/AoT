# coding=utf-8
# @ANCHOR: FUNCTION_LOADER
"""
FunctionLoader — trusted gateway for writing and loading AI-generated AbstractFunction subclasses.

Design ref: 035_PHASE_5_DETAILED_SPECIFICATION.yaml (Section 1)
Law 1: New service file only — never modifies existing function files in aot/functions/.
Law 2: register_in_index() calls incremental_update.py --verify immediately after write.
Law 4: write_approved_function() follows .tmp -> rename -> .ready sequence internally.
Law 6: VERIFY OK stdout captured in contract['index_verify_stdout'] before REGISTERED state.

Security model:
  - AI agents call FunctionGenerationService.propose() — never FunctionLoader directly.
  - write_approved_function() requires contract['validation_status'] == 'APPROVED'.
  - Path traversal check is non-bypassable: SecurityError terminates the write.
  - No absolute paths in logic_source — regex check before write.
  - AbstractFunction subclass check prevents arbitrary class injection.
"""
import importlib.util
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Path constraint — all AI-generated function files must live here (relative to dev_root)
CUSTOM_FUNCTIONS_DIR = "aot/functions/custom_functions"

# Prohibited patterns in AI-generated logic source (Law hardcoding_prohibition)
_ABSOLUTE_PATH_RE = re.compile(r'^[/~]|[A-Za-z]:\\', re.MULTILINE)

# Prohibited call patterns — prevent arbitrary system access from AI-generated code
_PROHIBITED_CALLS = (
    'subprocess.run', 'os.system', 'eval(', 'exec(', '__import__(',
    'importlib.import_module',
)


class SecurityError(Exception):
    """Raised when a security constraint is violated in FunctionLoader."""


# @ANCHOR: AI_FUNCTION_REGISTRATION_FLOW
class FunctionLoader:
    """
    Trusted component that writes approved AI-generated function files and loads them
    into the current process without restart.
    Only FunctionLoader may write to aot/functions/custom_functions/.
    AI agents NEVER write directly to this directory.

    @phase active
    @stability stable
    """

    @classmethod
    def write_approved_function(cls, contract: Dict[str, Any], logic_source: str) -> str:
        """
        Write an approved AI-generated function to aot/functions/custom_functions/.

        Implements Law 4 (3-Phase Stability):
          1. Write logic_source to '{target_path}.tmp'
          2. Wait 2.0s (sync client stability delay)
          3. os.rename('.tmp' -> target_path)  — atomic on POSIX
          4. Touch '{target_path}.ready' marker file

        Args:
            contract:     FunctionContract dict with validation_status='APPROVED',
                          source_type='AI_GENERATED', file_path, entry_class.
            logic_source: Python source code for the AbstractFunction subclass.

        Returns:
            Relative file_path of the written function file (after VERIFY OK).

        Raises:
            SecurityError:    Path traversal or prohibited pattern detected.
            PermissionError:  Contract not APPROVED or not AI_GENERATED.
            IOError:          File write failure.
            RuntimeError:     Index registration failed (VERIFY OK not received).
        """
        # ── Pre-condition checks ──────────────────────────────────────────────
        if contract.get('validation_status') != 'APPROVED':
            raise PermissionError(
                "[FunctionLoader] Cannot write: validation_status="
                f"'{contract.get('validation_status')}' — must be 'APPROVED'."
            )
        if contract.get('source_type') != 'AI_GENERATED':
            raise PermissionError(
                "[FunctionLoader] Cannot write: source_type must be 'AI_GENERATED'."
            )

        # ── Step 1: Path validation (non-bypassable) ──────────────────────────
        raw_path = contract.get('file_path', '')
        target_path = os.path.normpath(raw_path)
        if not target_path.startswith(CUSTOM_FUNCTIONS_DIR):
            raise SecurityError(
                f"[FunctionLoader] Path traversal attempt rejected: '{target_path}' "
                f"is not within '{CUSTOM_FUNCTIONS_DIR}'. Write aborted."
            )

        entry_class = contract.get('entry_class', '')
        if not entry_class or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', entry_class):
            raise SecurityError(
                f"[FunctionLoader] Invalid entry_class identifier: '{entry_class}'."
            )

        # ── Step 2: Content validation ────────────────────────────────────────
        if not logic_source or not isinstance(logic_source, str):
            raise SecurityError("[FunctionLoader] logic_source must be a non-empty string.")

        if f'class {entry_class}' not in logic_source:
            raise SecurityError(
                f"[FunctionLoader] logic_source does not define 'class {entry_class}'."
            )

        if _ABSOLUTE_PATH_RE.search(logic_source):
            raise SecurityError(
                "[FunctionLoader] Absolute path detected in logic_source — "
                "Law hardcoding_prohibition violated. Write aborted."
            )

        for pattern in _PROHIBITED_CALLS:
            if pattern in logic_source:
                raise SecurityError(
                    f"[FunctionLoader] Prohibited call '{pattern}' in logic_source. "
                    "Write aborted."
                )

        # ── Step 3: Law 4 write sequence (.tmp → 2s delay → rename → .ready) ─
        tmp_path = target_path + '.tmp'
        ready_path = target_path + '.ready'

        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            # Phase 1: Write .tmp
            with open(tmp_path, 'w', encoding='utf-8') as fh:
                fh.write(logic_source)
            logger.debug("[FunctionLoader][Law4] Written .tmp: %s", tmp_path)

            # Stability delay — prevents sync client race (Local_RULES Law 4)
            time.sleep(2.0)

            # Phase 2: Atomic rename
            os.rename(tmp_path, target_path)
            logger.info("[FunctionLoader][Law4] Renamed .tmp -> %s", target_path)

            # Phase 3: Touch .ready marker
            with open(ready_path, 'w', encoding='utf-8') as fh:
                fh.write('')
            logger.info("[FunctionLoader][Law4] .ready created: %s", ready_path)

        except Exception as exc:
            # Cleanup .tmp on write failure
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise IOError(
                f"[FunctionLoader] Write failed for '{target_path}': {exc}"
            ) from exc

        # ── Step 4: Index registration (VERIFY OK required before returning) ──
        cls.register_in_index(contract)

        logger.info(
            "[FunctionLoader] '%s' written, registered. file=%s",
            entry_class, target_path,
        )
        return target_path

    @classmethod
    def load_function(cls, file_path: str, contract: Dict[str, Any] = None) -> type:
        """
        Load an AbstractFunction subclass from file_path into the current runtime.

        Args:
            file_path: Relative path to the .py function file (within CUSTOM_FUNCTIONS_DIR).
            contract:  Optional FunctionContract dict; used to resolve entry_class name.

        Returns:
            The AbstractFunction subclass (uninstantiated class object).

        Raises:
            RuntimeError: .ready marker absent.
            SecurityError: file_path not within CUSTOM_FUNCTIONS_DIR.
            ImportError:   entry_class not found in loaded module.
            TypeError:     Loaded class does not extend AbstractFunction.
        """
        # ── Path constraint ───────────────────────────────────────────────────
        norm_path = os.path.normpath(file_path)
        if not norm_path.startswith(CUSTOM_FUNCTIONS_DIR):
            raise SecurityError(
                f"[FunctionLoader] Cannot load from '{norm_path}' — "
                f"must be within '{CUSTOM_FUNCTIONS_DIR}'."
            )

        # ── Step 1: .ready check (Law 4) ──────────────────────────────────────
        ready_path = file_path + '.ready'
        if not os.path.exists(ready_path):
            raise RuntimeError(
                f"[FunctionLoader] .ready marker absent for '{file_path}' — "
                "file not in READY state. Cannot load."
            )

        # ── Step 2: importlib load (no subprocess, no restart) ────────────────
        stem = os.path.splitext(os.path.basename(norm_path))[0]
        module_name = 'aot.functions.custom_functions.' + stem
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(
                f"[FunctionLoader] Cannot create module spec for '{file_path}'."
            )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # ── Step 3: Register in sys.modules ───────────────────────────────────
        sys.modules[module_name] = mod
        logger.info(
            "[FunctionLoader] Loaded '%s' -> sys.modules['%s']", file_path, module_name
        )

        # ── Step 4: Class extraction & AbstractFunction subclass check ────────
        entry_class_name = (contract or {}).get('entry_class') or stem
        loaded_cls = getattr(mod, entry_class_name, None)
        if loaded_cls is None:
            raise ImportError(
                f"[FunctionLoader] Class '{entry_class_name}' not found in '{file_path}'."
            )

        try:
            from aot.functions.base_function import AbstractFunction
            if not issubclass(loaded_cls, AbstractFunction):
                raise TypeError(
                    f"[FunctionLoader] '{entry_class_name}' does not extend AbstractFunction. "
                    "Arbitrary class injection rejected."
                )
        except ImportError:
            logger.warning(
                "[FunctionLoader] AbstractFunction unavailable — subclass check skipped."
            )

        logger.info("[FunctionLoader] Class '%s' loaded successfully.", entry_class_name)
        return loaded_cls

    @classmethod
    def register_in_index(cls, contract: Dict[str, Any]) -> None:
        """
        Trigger incremental_update.py --verify for the new function file.
        Stores raw VERIFY OK stdout in contract['index_verify_stdout'] (Law 6 evidence).

        Args:
            contract: FunctionContract dict with 'file_path' key.

        Raises:
            RuntimeError: VERIFY OK not in stdout — index sync failed.
        """
        file_path = contract.get('file_path', '')
        from aot.config import INSTALL_DIRECTORY
        
        base_dir = os.path.dirname(INSTALL_DIRECTORY)
        indexer_path = os.path.join(base_dir, '2603_symbolic_index_generator', 'Build', 'incremental_update.py')
        source_dir = os.path.join(INSTALL_DIRECTORY, 'Build', '5_docker')
        output_dir = os.path.join(source_dir, 'anchor_index')

        cmd = [
            'python3',
            indexer_path,
            '--source-dir', source_dir,
            '--output-dir', output_dir,
            '--files', file_path,
            '--verify',
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            stdout = result.stdout or ''
            stderr = result.stderr or ''

            if 'VERIFY OK' not in stdout:
                raise RuntimeError(
                    f"[FunctionLoader] Index sync failed for '{file_path}': "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )

            # Law 6: store raw stdout as verifiable evidence
            contract['index_verify_stdout'] = stdout.strip()
            logger.info(
                "[FunctionLoader] VERIFY OK — '%s' indexed. stdout: %s",
                file_path, stdout.strip(),
            )

        except subprocess.TimeoutExpired:
            logger.warning(
                "[FunctionLoader] incremental_update.py timed out for '%s' — "
                "file written but not yet indexed.", file_path
            )
            raise RuntimeError(
                f"[FunctionLoader] Index registration timed out for '{file_path}'."
            )
