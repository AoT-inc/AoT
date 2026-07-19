# -*- coding: utf-8 -*-
"""Generate lightweight JSON index of Markdown documentation for AI RAG."""
import os
import re
import json

import sys
sys.path.append(os.path.abspath(os.path.join(__file__, "../../..")))

from aot.config import INSTALL_DIRECTORY

DOCS_DIR = os.path.join(INSTALL_DIRECTORY, "docs")
AI_DOCS_DIR = os.path.join(DOCS_DIR, "ai_docs")

def generate_index():
    """Build a JSON section index from Markdown docs for AI RAG lookup.

    Parses all non-translation .md files in the docs directory, extracts
    level-2 and level-3 headers, and writes a deduplicated index to
    ai_docs/ai_doc_index.json.

    @phase doc-generation
    @dependency aot.config
    """
    if not os.path.exists(AI_DOCS_DIR):
        os.makedirs(AI_DOCS_DIR)
        
    index_data = {}
    
    # Regex to match Markdown headers (e.g., "## section name")
    header_pattern = re.compile(r'^(#{1,4})\s+(.+)$')
    
    # Exclude files that are translation variants (e.g., .ko.md, .es.md)
    # and files that might not be useful for system technical knowledge.
    exclude_prefixes = ['About', 'index', 'map']
    
    for filename in os.listdir(DOCS_DIR):
        if not filename.endswith('.md'):
            continue
            
        # Check for language variants (matches .xx.md or .xxx.md)
        parts = filename.split('.')
        if len(parts) > 2 and len(parts[-2]) in (2, 3):
            continue
            
        # Check exclude prefixes
        if any(filename.startswith(prefix) for prefix in exclude_prefixes):
            continue
            
        file_path = os.path.join(DOCS_DIR, filename)
        
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
                    
            if unique_sections:
                index_data[filename] = unique_sections
                
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            
    output_file = os.path.join(AI_DOCS_DIR, "ai_doc_index.json")
    with open(output_file, "w", encoding='utf-8') as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ AI Markdown Index generated successfully at: {output_file}")

if __name__ == "__main__":
    generate_index()
