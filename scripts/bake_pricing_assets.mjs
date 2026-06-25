#!/usr/bin/env node
/**
 * Regenerate worker/src/lib/pricing_data_assets.ts from config/pricing.json.
 *
 * The Workers runtime can't read JSON files, so we bake the hand-curated
 * pricing into a TypeScript module that ships in the worker bundle. This
 * serves as the baseline before the first cron-triggered OpenRouter refresh
 * writes to KV.
 *
 * Usage:
 *     node scripts/bake_pricing_assets.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const repoRoot = resolve(import.meta.dirname, '..');
const sourcePath = resolve(repoRoot, 'config', 'pricing.json');
const destPath = resolve(repoRoot, 'worker', 'src', 'lib', 'pricing_data_assets.ts');

const raw = JSON.parse(readFileSync(sourcePath, 'utf-8'));
const models = raw.models ?? {};
const entries = Object.entries(models);

const header = `/**
 * Baked-in copy of config/pricing.json (${entries.length} hand-curated models).
 *
 * The Cloudflare Workers runtime has no fs module, so we embed the
 * hand-curated pricing as a TypeScript object literal. This serves as the
 * baseline pricing before the first cron-triggered OpenRouter refresh writes
 * to KV.
 *
 * If you edit config/pricing.json, regenerate this file by running:
 *     node scripts/bake_pricing_assets.mjs
 *
 * (Source-of-truth: config/pricing.json. Worker bundle: this file.)
 */

export const PRICING_BLOB = `;

const body = JSON.stringify(raw, null, 2) + ' as const;\n';

writeFileSync(destPath, header + body);
console.log(`Wrote ${destPath} (${entries.length} models)`);