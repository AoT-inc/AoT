#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automate version bumps across config, docs, and changelog for a release."""
import argparse
import os
import re
import sys
import subprocess
from datetime import datetime

# Configuration
# AOT_VERSION lives in the config package's __init__ (aot/config/__init__.py).
# It used to be a single module aot/config.py; after the merge into a package
# this path was left stale, so version bumps here silently failed with
# FileNotFoundError — a likely cause of the inconsistent release tags.
CONFIG_FILE = 'aot/config/__init__.py'
MKDOCS_FILE = 'mkdocs.yml'
README_FILES = (
    ('README.md', r"Latest version: [\d\.]+", "Latest version: {v}"),
    ('README.ko.md', r"최신 버전: [\d\.]+", "최신 버전: {v}"),
)
CHANGELOG_FILE = 'CHANGELOG.md'
GENERATE_SCRIPT = 'aot/scripts/generate_all.sh'

def get_current_version(file_path):
    """Extract the current AOT_VERSION string from the given config file.

    @phase release
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r"AOT_VERSION = '([\d\.]+)'", content)
        if match:
            return match.group(1)
    return None

def update_file(file_path, pattern, replacement, dry_run=False):
    """Apply a regex substitution to a file, optionally in dry-run mode.

    @phase release
    """
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

UNRELEASED_HEADING = '# 미출시 (Unreleased)'
UNRELEASED_NOTE = (
    "_다음 판에 들어갈 항목은 이 절 아래에 적습니다. 아래의 릴리스 절에 추가하지 마세요 —\n"
    "이미 배포된 판의 문서가 실제 설치본과 어긋납니다._"
)


def promote_unreleased(content, version, date_str, title=None):
    """「미출시」 절을 `# vX (날짜)` 릴리스 절로 승격하고, 그 위에 빈 「미출시」 절을 새로 연다.

    CHANGELOG 는 평소 「미출시」 절에만 적는다. 릴리스 때는 그 절의 이름만 바꾸면 되고,
    새 뼈대를 끼워 넣지 않는다(옛 동작 — 태그 뒤에 릴리스 절에 항목이 더해지던 함정의 뿌리).

    반환: (새 본문, 상태). 상태는 'promoted' | 'exists' | 'no_unreleased' | 'empty'.
    """
    if re.search(r'^# v%s \(' % re.escape(version), content, re.M):
        return content, 'exists'
    lines = content.split('\n')
    try:
        start = lines.index(UNRELEASED_HEADING)
    except ValueError:
        return content, 'no_unreleased'
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == '---'),
               len(lines))
    body = '\n'.join(lines[start + 1:end]).strip('\n')
    body = body.replace(UNRELEASED_NOTE, '').strip('\n')
    if not body:
        return content, 'empty'

    heading = '# v%s (%s)' % (version, date_str)
    if title:
        heading += ' — %s' % title
    fresh = [UNRELEASED_HEADING, '', UNRELEASED_NOTE, '', '---', '', heading, '']
    new_lines = lines[:start] + fresh + body.split('\n') + [''] + lines[end:]
    return '\n'.join(new_lines), 'promoted'


def update_changelog(version, date_str, title=None, dry_run=False):
    """CHANGELOG.md 의 「미출시」 절을 릴리스 절로 승격한다.

    @phase release
    """
    print(f"Updating {CHANGELOG_FILE}...")
    with open(CHANGELOG_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content, status = promote_unreleased(content, version, date_str, title)
    if status == 'exists':
        print(f"Changelog entry for {version} already exists.")
        return
    if status == 'no_unreleased':
        print(f"Error: '{UNRELEASED_HEADING}' 절이 없습니다. 항목을 그 절에 적은 뒤 다시 실행하세요.")
        sys.exit(1)
    if status == 'empty':
        print("Error: 「미출시」 절이 비어 있습니다. 이 판에 들어가는 항목을 먼저 적으세요"
              " (git log <직전태그>..HEAD 로 역추적).")
        sys.exit(1)
    if dry_run:
        print(f"[DRY RUN] Would promote 「미출시」 → v{version} ({date_str}) and open a new empty 「미출시」 절")
        return
    with open(CHANGELOG_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Promoted 「미출시」 → 릴리스 절. 첫 소절 제목에 compare 링크"
          "(.../compare/v<직전>...v<이번>)는 손으로 붙이세요.")

def run_generate_script(dry_run=False):
    """Execute generate_all.sh to regenerate derived release artifacts.

    **기본 릴리스 절차에서는 호출하지 않는다(--generate 로만).** 매뉴얼 생성기가 MQTT
    기본 client_XXXXXXXX 를 매번 랜덤으로 뽑아 무의미한 diff 를 만들고, 스크립트 안의
    번역 재추출이 fuzzy 대량 오역을 낼 수 있다(CLAUDE.md "릴리스" 절 참고).

    @phase release
    @dependency subprocess
    """
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
    """Orchestrate a full version bump across all release-sensitive files.

    @phase release
    """
    parser = argparse.ArgumentParser(description='AoT Release Helper')
    parser.add_argument('new_version', help='New version number (e.g. 8.17.2)')
    parser.add_argument('--check', action='store_true', help='Dry-run mode to check what would happen')
    parser.add_argument('--title', default=None,
                        help='릴리스 절 제목의 "— 제목" 부분(선택)')
    parser.add_argument('--generate', action='store_true',
                        help='generate_all.sh 도 실행(기본은 실행하지 않음 — 함정 있음)')
    
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

    # 0. CHANGELOG.md: 「미출시」 절을 릴리스 절로 승격.
    #    실패할 수 있는 단계(절 없음·본문 비어 있음)라 다른 파일을 건드리기 전에 먼저 한다.
    today = datetime.now().strftime('%Y-%m-%d')
    update_changelog(args.new_version, today, args.title, args.check)

    # 1. Update AOT_VERSION in the config package (aot/config/__init__.py)
    update_file(CONFIG_FILE,
                r"AOT_VERSION = '[\d\.]+'", 
                f"AOT_VERSION = '{args.new_version}'", 
                args.check)

    # 2. Update mkdocs.yml
    update_file(MKDOCS_FILE, 
                r"version: [\d\.]+", 
                f"version: {args.new_version}", 
                args.check)

    # 3. Update README.md / README.ko.md
    for readme, pattern, template in README_FILES:
        update_file(readme, pattern,
                    template.format(v=args.new_version),
                    args.check)

    # 4. 생성 스크립트는 명시했을 때만 돌린다
    if args.generate and not args.check:
        run_generate_script(args.check)
    elif args.generate:
        print("[DRY RUN] Would execute generate_all.sh")
    else:
        print("Skipping generate_all.sh (필요하면 --generate; 매뉴얼만 갱신하려면 "
              "aot/scripts/generate_manual_*.py 를 개별 실행)")

    print("\nDone! Please review changes.")
    print(f"1. Check {CONFIG_FILE}")
    print(f"2. Check {MKDOCS_FILE}")
    print("3. Check README.md / README.ko.md")
    print(f"4. Check {CHANGELOG_FILE} (승격된 절 + 새 빈 「미출시」 절)")
    print("5. Commit → PR → 머지 (그다음 비공개 태그 → 발행: CLAUDE.md \"릴리스\" 절)")

if __name__ == '__main__':
    main()
