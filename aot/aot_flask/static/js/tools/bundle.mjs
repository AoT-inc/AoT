#!/usr/bin/env node
/**
 * Global-script bundler for AoT static JS.
 *
 * These files are CLASSIC global-scope scripts (not ES modules). We must NOT
 * wrap them in a module/IIFE scope (would hide top-level `var`/`function`
 * globals) and must NOT rename top-level identifiers. So we:
 *   1. concatenate inputs in order, separated by "\n;\n" (ASI safety),
 *   2. minify with esbuild transform mode (script semantics, top-level names
 *      preserved — esbuild does not rename top-level identifiers in transform
 *      mode because they may be referenced externally).
 *
 * Result is behavior-equivalent to loading the same files as separate <script>
 * tags in the same order, just minified into one request.
 *
 * Usage: node tools/bundle.mjs [bundleName ...]   (default: all in bundles.json)
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import * as esbuild from 'esbuild';

const ROOT = dirname(fileURLToPath(import.meta.url)) + '/..'; // static/js
const cfg = JSON.parse(readFileSync(join(ROOT, 'tools', 'bundles.json'), 'utf8'));
const MANIFEST = join(ROOT, 'dist', 'manifest.json');

const wanted = process.argv.slice(2);
const names = wanted.length ? wanted : Object.keys(cfg);

// Load existing manifest so a single-bundle build doesn't drop other entries.
let manifest = {};
try { manifest = JSON.parse(readFileSync(MANIFEST, 'utf8')); } catch {}

for (const name of names) {
  const b = cfg[name];
  if (!b) { console.error(`unknown bundle: ${name}`); process.exit(1); }
  const parts = [];
  for (const rel of b.inputs) {
    const p = resolve(ROOT, rel);
    if (!existsSync(p)) { console.error(`[${name}] missing input: ${rel}`); process.exit(1); }
    parts.push(`/* >>> ${rel} */`);
    parts.push(readFileSync(p, 'utf8'));
  }
  const joined = parts.join('\n;\n');
  const res = await esbuild.transform(joined, {
    minify: true,
    legalComments: 'none',
    // transform mode (no bundle) => top-level identifiers preserved (globals intact)
  });
  const outPath = resolve(ROOT, b.output);
  mkdirSync(dirname(outPath), { recursive: true });
  const banner = `/* AoT bundle: ${name} — built from ${b.inputs.length} sources. Do not edit; edit sources and rebuild (tools/bundle.mjs). */\n`;
  const out = banner + res.code;
  writeFileSync(outPath, out);
  // content-hash for cache-busting (?v=<hash>) — see Flask asset() helper.
  const hash = createHash('sha256').update(out).digest('hex').slice(0, 10);
  manifest[name] = hash;
  const kb = (Buffer.byteLength(out) / 1024).toFixed(1);
  console.log(`[${name}] ${b.inputs.length} files -> ${b.output} (${kb} KB) v=${hash}`);
}

// Persist manifest: bundle name -> content hash (used by Flask asset()).
mkdirSync(dirname(MANIFEST), { recursive: true });
const ordered = {};
for (const k of Object.keys(manifest).sort()) ordered[k] = manifest[k];
writeFileSync(MANIFEST, JSON.stringify(ordered, null, 2) + '\n');
console.log(`manifest -> dist/manifest.json (${Object.keys(ordered).length} entries)`);
