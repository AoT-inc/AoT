#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import importlib.util

def check_command(cmd):
    """Check if a system command exists."""
    try:
        subprocess.check_output(["which", cmd])
        return True
    except subprocess.CalledProcessError:
        return False

def check_python_package(package_name):
    """Check if a python package is installed in the current environment."""
    spec = importlib.util.find_spec(package_name)
    return spec is not None

def get_package_version(package_name):
    """Get the version of an installed python package."""
    try:
        import pkg_resources
        return pkg_resources.get_distribution(package_name).version
    except Exception:
        try:
            import importlib.metadata
            return importlib.metadata.version(package_name)
        except Exception:
            return "Unknown"

def validate_indices(indices_path):
    """Check if anchor_index JSON files exist and are readable."""
    required_indices = [
        "aot_inputs.json",
        "aot_devices.json",
        "aot_utils.json"
    ]
    results = {}
    for index in required_indices:
        full_path = os.path.join(indices_path, index)
        if os.path.exists(full_path):
            try:
                with open(full_path, 'r') as f:
                    json.load(f)
                results[index] = "OK"
            except Exception as e:
                results[index] = f"Error: {str(e)}"
        else:
            results[index] = "Missing"
    return results

def main():
    print("=== AoT Pre-installation System Check ===")
    
    # 1. System Level Check
    print("\n1. System Level Check:")
    ts_exists = check_command("ts")
    print(f"  [ {'OK' if ts_exists else 'FAILED'} ] 'ts' command (moreutils)")
    if not ts_exists:
        print("     -> Hint: Run 'sudo apt install moreutils' on target system.")

    # 2. Virtual Environment Check
    print("\n2. Virtual Environment Check:")
    smbus_exists = check_python_package("smbus2")
    if smbus_exists:
        version = get_package_version("smbus2")
        print(f"  [ OK ] 'smbus2' package (Version: {version})")
    else:
        print("  [ FAILED ] 'smbus2' package not found")
        print("     -> Hint: Run 'pip install smbus2==0.4.1' in your virtualenv.")

    # 3. anchor_index Check
    print("\n3. anchor_index Validation:")
    indices_path = "/Users/gwansuk/Documents/GitHub/AoT/anchro_index/indices"
    index_results = validate_indices(indices_path)
    for name, status in index_results.items():
        print(f"  [ {'OK' if status == 'OK' else 'FAILED'} ] {name}: {status}")

    print("\n=== Check Complete ===")
    
    if not ts_exists or not smbus_exists or any(s != "OK" for s in index_results.values()):
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
