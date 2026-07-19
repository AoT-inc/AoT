#!/usr/bin/env python3
"""Static asset reference checker.

Scans templates (*.html), widget sources (aot/widgets/*.py) and generated
user_templates for /static/(js|css)/... references and verifies each referenced
file exists on disk. Use as a regression net when moving/renaming static assets.

Exit code 0 = all references resolve; 1 = missing references found.
"""
import os, re, sys, json

# aot/scripts/check_static_refs.py -> repo root is three levels up
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC = os.path.join(ROOT, "aot", "aot_flask", "static")
SCAN_DIRS = [
    os.path.join(ROOT, "aot", "aot_flask", "templates"),
    os.path.join(ROOT, "aot", "widgets"),
]
SCAN_EXT = (".html", ".py", ".js")
# Two reference styles:
#   literal:  /static/js/foo.js   /static/css/bar.css
#   url_for:  url_for('static', filename='js/foo.js')
REF_RES = [
    re.compile(r"/static/((?:js|css)/[A-Za-z0-9_./-]+\.(?:js|css))"),
    re.compile(r"""filename=['"]((?:js|css)/[A-Za-z0-9_./-]+\.(?:js|css))['"]"""),
]

def iter_files():
    for base in SCAN_DIRS:
        for dp, _, fns in os.walk(base):
            for fn in fns:
                if fn.endswith(SCAN_EXT):
                    yield os.path.join(dp, fn)

ASSET_RE = re.compile(r"""asset\(\s*['"]([A-Za-z0-9_./-]+)['"]\s*\)""")
DIST = os.path.join(STATIC, "js", "dist")
MANIFEST = os.path.join(DIST, "manifest.json")


def check_bundles():
    """Validate asset('<name>') refs against dist/manifest.json + on-disk bundles.

    Replaces the literal-path regression net for JS that moved to the content-hash
    asset() helper. Returns (problems:int).
    """
    try:
        manifest = json.load(open(MANIFEST, encoding="utf-8"))
    except Exception as e:
        manifest = None
        manifest_err = str(e)
    used = {}  # name -> set(source files)
    for path in iter_files():
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            continue
        for name in ASSET_RE.findall(txt):
            used.setdefault(name, set()).add(os.path.relpath(path, ROOT))
    problems = 0
    if used and manifest is None:
        print(f"asset() used but manifest unreadable: {manifest_err}")
        return len(used)
    for name in sorted(used):
        bundle = os.path.join(DIST, name + ".bundle.js")
        if manifest is not None and name not in manifest:
            print(f"  - asset('{name}') has no manifest entry  <- {sorted(used[name])}")
            problems += 1
        if not os.path.exists(bundle):
            print(f"  - asset('{name}') bundle missing: js/dist/{name}.bundle.js")
            problems += 1
    # manifest entries whose bundle file is gone
    for name, h in (manifest or {}).items():
        if not os.path.exists(os.path.join(DIST, name + ".bundle.js")):
            print(f"  - manifest '{name}' -> missing js/dist/{name}.bundle.js")
            problems += 1
    print(f"asset() refs: {sum(len(v) for v in used.values())} "
          f"(distinct bundles: {len(used)}); manifest entries: {len(manifest or {})}")
    return problems


def main():
    missing = {}   # rel_asset -> set(source files)
    total = 0
    seen = set()
    for path in iter_files():
        try:
            txt = open(path, encoding="utf-8").read()
        except Exception:
            continue
        for rx in REF_RES:
            for m in rx.findall(txt):
                total += 1
                seen.add(m)
                disk = os.path.join(STATIC, m)
                if not os.path.exists(disk):
                    missing.setdefault(m, set()).add(os.path.relpath(path, ROOT))
    print(f"scanned refs: {total}  (distinct assets: {len(seen)})")
    bundle_problems = check_bundles()
    if missing:
        print(f"MISSING: {len(missing)} asset(s) referenced but not on disk:")
        for asset in sorted(missing):
            print(f"  - /static/{asset}")
            for src in sorted(missing[asset]):
                print(f"        <- {src}")
    if missing or bundle_problems:
        print(f"FAIL: {len(missing)} missing literal ref(s), {bundle_problems} bundle/manifest problem(s).")
        return 1
    print("OK: all static references resolve.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
