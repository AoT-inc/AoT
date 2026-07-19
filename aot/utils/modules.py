# coding=utf-8
import importlib.util
import logging
import os
import traceback

logger = logging.getLogger("aot.modules")


def load_module_from_file(path_file, module_type):
    """Load a Python module from a file path using importlib.

    @phase active
    @stability stable
    """
    try:
        module_name = "aot.{}.{}".format(
            module_type, os.path.basename(path_file).split('.')[0])
        spec = importlib.util.spec_from_file_location(module_name, path_file)
        if spec is None or spec.loader is None:
            return None, f"Could not create spec for: {path_file}"
        module_custom = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module_custom)
        return module_custom, "success"
    except Exception:
        logger.error(f"Path: {path_file}, Type: {module_type}")
        logger.error(f"Could not load module: {traceback.format_exc()}")
        return None, traceback.format_exc()
