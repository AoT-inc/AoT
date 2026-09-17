# -*- coding: utf-8 -*-
"""Generate lightweight JSON index of Markdown documentation for AI RAG."""
import os
import re
import json

import sys
sys.path.append(os.path.abspath(os.path.join(__file__, "../../..")))

try:
    from aot.config import INSTALL_DIRECTORY
except Exception:
    # This script only needs the project root, and it is run from CI checkouts
    # that install the docs toolchain but not the app's dependencies (aot.config
    # pulls in flask_babel). Fall back to this file's own position in the tree.
    INSTALL_DIRECTORY = os.path.abspath(os.path.join(__file__, "../../.."))

DOCS_DIR = os.path.join(INSTALL_DIRECTORY, "docs")
AI_DOCS_DIR = os.path.join(DOCS_DIR, "ai_docs")
MKDOCS_YML = os.path.join(INSTALL_DIRECTORY, "mkdocs.yml")

# Manual pages that are not in the mkdocs nav but that the AI still needs:
# generated catalogues and the AI's own guide.
EXTRA_DOCS = [
    'Supported-Geo-Layers.md',
    'General-Settings.md',
    'ai_guide.md',
]

# Pages that are in the nav (or on disk) but carry nothing worth indexing:
# redirect stubs and superseded technical notes.
SKIP_DOCS = {
    'index.md',
    'About.md',
    'GEO.md',
    'map.md',
}


def _nav_documents():
    """Return the .md paths listed in the mkdocs nav, in nav order.

    The nav is the line between user manual pages and the internal design
    notes that live in docs/ alongside them, so it also decides what the AI
    is allowed to see. Parsed with a regex rather than PyYAML: this script
    runs from a bare checkout with no build dependencies.

    @phase doc-generation
    """
    try:
        with open(MKDOCS_YML, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError as e:
        print(f"Could not read {MKDOCS_YML}: {e}")
        return []

    if 'nav:' not in content:
        return []
    nav_block = content.split('nav:', 1)[1]
    found = re.findall(r'([A-Za-z0-9_\-/\.]+\.md)', nav_block)

    ordered = []
    for name in found + EXTRA_DOCS:
        if name in SKIP_DOCS or name in ordered:
            continue
        ordered.append(name)
    return ordered


def generate_index():
    """Build a JSON section index from Markdown docs for AI RAG lookup.

    Walks the manual pages listed in the mkdocs nav, extracts level-2 and
    level-3 headers, and writes a deduplicated index to
    ai_docs/ai_doc_index.json. Keys are paths relative to docs/, which is
    exactly what read_manual takes as its target_id.

    @phase doc-generation
    @dependency aot.config
    """
    if not os.path.exists(AI_DOCS_DIR):
        os.makedirs(AI_DOCS_DIR)
        
    index_data = {}
    
    # Regex to match Markdown headers (e.g., "## section name")
    header_pattern = re.compile(r'^(#{1,4})\s+(.+)$')
    
    for filename in _nav_documents():
        # Skip language variants (matches .xx.md or .xxx.md); the nav only
        # lists the English originals, but EXTRA_DOCS could name one.
        parts = filename.split('.')
        if len(parts) > 2 and len(parts[-2]) in (2, 3):
            continue
            
        file_path = os.path.join(DOCS_DIR, filename)
        if not os.path.exists(file_path):
            print(f"Listed in nav but missing: {filename}")
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            sections = []
            for line in lines:
                match = header_pattern.match(line.strip())
                if match:
                    level = len(match.group(1))
                    title = match.group(2).strip()
                    # Strip explicit attr_list anchors (e.g. "Dashboard { #dashboard }")
                    title = re.sub(r'\s*\{[^}]*\}\s*$', '', title).strip()
                    # Reduce a markdown link header to its text (greedy handles
                    # nested brackets, e.g. "[RainViewer [Discontinued]](url)" -> text)
                    title = re.sub(r'\[(.+)\]\([^)]*\)', r'\1', title).strip()
                    # Include level 2 and 3 headers primarily for granular indexing
                    if 2 <= level <= 3:
                        sections.append(title)
            
            # Deduplicate while preserving order
            seen = set()
            unique_sections = []
            for sec in sections:
                if sec not in seen:
                    unique_sections.append(sec)
                    seen.add(sec)
                    
            # Short pages (Alerts, Energy-Usage, ...) carry no level-2 header
            # at all. They are still indexed, with an empty section list, so
            # the AI knows the page exists and can read it whole.
            index_data[filename] = unique_sections
                
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            
    output_file = os.path.join(AI_DOCS_DIR, "ai_doc_index.json")
    with open(output_file, "w", encoding='utf-8') as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ AI Markdown Index generated successfully at: {output_file}")

if __name__ == "__main__":
    generate_index()
