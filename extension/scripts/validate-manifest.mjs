#!/usr/bin/env node
// Chrome MV3 manifest validator. web-ext lint is Firefox-only and rejects
// background.service_worker, so we hand-roll a small structural check.
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const manifestPath = join(root, 'manifest.json');

const errors = [];
const warnings = [];

let manifest;
try {
  manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
} catch (err) {
  console.error(`manifest.json is not valid JSON: ${err.message}`);
  process.exit(1);
}

function must(condition, message) {
  if (!condition) errors.push(message);
}


function warn(condition, message) {
  if (!condition) warnings.push(message);
}

must(manifest.manifest_version === 3, 'manifest_version must be 3');
must(typeof manifest.name === 'string' && manifest.name.length > 0, 'name is required');
must(/^\d+\.\d+\.\d+$/.test(manifest.version), 'version must be semver-like X.Y.Z');
must(typeof manifest.description === 'string' && manifest.description.length > 0, 'description is required');
must(Array.isArray(manifest.permissions), 'permissions must be an array');
must(Array.isArray(manifest.host_permissions), 'host_permissions must be an array');

const sw = manifest.background?.service_worker;
must(typeof sw === 'string' && sw.endsWith('.js'), 'background.service_worker must reference a .js file');
if (sw) {
  must(existsSync(join(root, sw)), `background.service_worker file not found: ${sw}`);
}

must(Array.isArray(manifest.content_scripts) && manifest.content_scripts.length > 0, 'content_scripts must be a non-empty array');
for (const cs of manifest.content_scripts ?? []) {
  must(Array.isArray(cs.matches) && cs.matches.length > 0, 'content_scripts[].matches must be a non-empty array');
  must(Array.isArray(cs.js) && cs.js.length > 0, 'content_scripts[].js must be a non-empty array');
  for (const file of cs.js ?? []) {
    must(existsSync(join(root, file)), `content_scripts js file not found: ${file}`);
  }
}

must(typeof manifest.action?.default_popup === 'string', 'action.default_popup is required');
if (manifest.action?.default_popup) {
  must(existsSync(join(root, manifest.action.default_popup)), `action.default_popup file not found: ${manifest.action.default_popup}`);
}

for (const [size, icon] of Object.entries(manifest.icons ?? {})) {
  must(existsSync(join(root, icon)), `icons[${size}] file not found: ${icon}`);
}

warn(manifest.permissions?.includes('alarms'), 'alarms permission missing — needed for MV3 service-worker scheduling');

if (errors.length > 0) {
  console.error('manifest.json validation FAILED:');
  for (const e of errors) console.error(`  ✗ ${e}`);
  process.exit(1);
}

if (warnings.length > 0) {
  console.warn('manifest.json warnings:');
  for (const w of warnings) console.warn(`  ⚠ ${w}`);
}

console.log(`manifest.json OK (${manifest.name} v${manifest.version}, MV3)`);
