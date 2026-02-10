#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import os
import re
import sys
import subprocess
from datetime import datetime

# Configuration
CONFIG_FILE = 'aot/config.py'
MKDOCS_FILE = 'mkdocs.yml'
README_FILE = 'README.rst'
CHANGELOG_FILE = 'CHANGELOG.md'
GENERATE_SCRIPT = 'aot/scripts/generate_all.sh'

def get_current_version(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r"AOT_VERSION = '([\d\.]+)'", content)
        if match:
            return match.group(1)
    return None

def update_file(file_path, pattern, replacement, dry_run=False):
    print(f"Updating {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content, count = re.subn(pattern, replacement, content)
    
    if count == 0:
        print(f"Warning: No match found for pattern in {file_path}")
        return False
    
    if not dry_run:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    else:
        print(f"[DRY RUN] Would write to {file_path}")
    
    return True

def update_changelog(version, date_str, dry_run=False):
    print(f"Updating {CHANGELOG_FILE}...")
    entry_header = f"## {version} ({date_str})"
    
    # Check if entry already exists
    with open(CHANGELOG_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
        if entry_header in content:
            print(f"Changelog entry for {version} already exists.")
            return

    new_entry = f"{entry_header}\n\n### Bugfixes\n- \n\n### Features\n- \n\n### Miscellaneous\n- \n\n"
    
    if not dry_run:
        # Prepend after the first header or specific marker if we had one. 
        # For now, let's just insert it after the main title if possible, or at the top.
        # Assuming typical changelog format, we insert after the first line (Title)
        lines = content.splitlines()
        # Find where to insert (usually after the title)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith('# '): # Main title
                insert_idx = i + 1
                break
        
        lines.insert(insert_idx, "")
        lines.insert(insert_idx + 1, new_entry.strip())
        
        with open(CHANGELOG_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    else:
        print(f"[DRY RUN] Would prepend to {CHANGELOG_FILE}:\n{new_entry}")

def run_generate_script(dry_run=False):
    print(f"Running generation script: {GENERATE_SCRIPT}")
    if not dry_run:
        try:
            subprocess.check_call(['bash', GENERATE_SCRIPT])
        except subprocess.CalledProcessError as e:
            print(f"Error running generation script: {e}")
            sys.exit(1)
    else:
        print("[DRY RUN] Would execute generate_all.sh")

def main():
    parser = argparse.ArgumentParser(description='AoT Release Helper')
    parser.add_argument('new_version', help='New version number (e.g. 8.17.2)')
    parser.add_argument('--check', action='store_true', help='Dry-run mode to check what would happen')
    
    args = parser.parse_args()
    
    # Change to root dir
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
    os.chdir(root_dir)
    print(f"Working directory: {root_dir}")

    current_version = get_current_version(CONFIG_FILE)
    print(f"Current version: {current_version}")
    print(f"Target version:  {args.new_version}")
    
    if not re.match(r'^\d+\.\d+\.\d+$', args.new_version):
        print("Error: Version must be in format MAJOR.MINOR.BUGFIX (e.g. 8.17.2)")
        sys.exit(1)

    # 1. Update config.py
    update_file(CONFIG_FILE, 
                r"AOT_VERSION = '[\d\.]+'", 
                f"AOT_VERSION = '{args.new_version}'", 
                args.check)

    # 2. Update mkdocs.yml
    update_file(MKDOCS_FILE, 
                r"version: [\d\.]+", 
                f"version: {args.new_version}", 
                args.check)

    # 3. Update README.rst
    update_file(README_FILE,
                 r"최신 버전: [\d\.]+",
                 f"최신 버전: {args.new_version}",
                 args.check)

    # 4. Update CHANGELOG.md
    today = datetime.now().strftime('%Y-%m-%d')
    update_changelog(args.new_version, today, args.check)

    # 5. Run generation scripts
    if not args.check:
        run_generate_script(args.check)
    else:
        print("[DRY RUN] Skipping generator script execution")

    print("\nDone! Please review changes.")
    print(f"1. Check {CONFIG_FILE}")
    print(f"2. Check {MKDOCS_FILE}")
    print(f"3. Check {README_FILE}")
    print(f"4. Fill in {CHANGELOG_FILE}")
    print("5. Commit and push")

if __name__ == '__main__':
    main()
