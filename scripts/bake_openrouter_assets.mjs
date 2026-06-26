#!/usr/bin/env node
/**
 * Regenerate worker/src/lib/openrouter_data_assets.ts from worker/config/openrouter.json.
 *
 * The Workers runtime can't read JSON files, so we bake the OpenRouter cache
 * into a TypeScript module that ships in the worker bundle. The Cloudflare
 * Worker uses this as the second fallback (after PRICING_BLOB) when KV is
 * empty — combined they give the full ~347 models on first request, with no
 * waiting for the cron trigger.
 *
 * Usage:
 *     node scripts/bake_openrouter_assets.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const repoRoot = resolve(import.meta.dirname, '..');
const sourcePath = resolve(repoRoot, 'worker', 'config', 'openrouter.json');
const destPath = resolve(repoRoot, 'worker', 'src', 'lib', 'openrouter_data_assets.ts');

const raw = JSON.parse(readFileSync(sourcePath, 'utf-8'));
const models = raw.models ?? {};
const entries = Object.entries(models);

const header = `/**
 * Baked-in copy of worker/config/openrouter.json (${entries.length} live models).
 *
 * The Cloudflare Workers runtime has no fs module, so we embed the
 * OpenRouter cache as a TypeScript object literal. This serves as the
 * second-tier fallback after PRICING_BLOB when KV is empty — combined they
 * give the full model set on first request, with no waiting for the cron
 * trigger to populate KV.
 *
 * If you edit worker/config/openrouter.json, regenerate this file by running:
 *     node scripts/bake_openrouter_assets.mjs
 *
 * (Source-of-truth: worker/config/openrouter.json. Worker bundle: this file.
 *  Same shape as PRICING_BLOB: { _meta, models: { model_id: ModelPricing } }.)
 */

export const OPENROUTER_BLOB = `;

const body = JSON.stringify(raw, null, 2) + ' as const;\n';

writeFileSync(destPath, header + body);
console.log(`Wrote ${destPath} (${entries.length} models)`);
