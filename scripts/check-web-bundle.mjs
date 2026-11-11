#!/usr/bin/env node
// Fails if anything secret from the repository's .env files ended up in the web build.
//
// The root .env holds database credentials next to the web app's public settings. This is
// the regression check that the web build never sees them: it scans every file the build
// produced for the names and values of sensitive variables.
//
// Usage: node scripts/check-web-bundle.mjs [build-directory]   (default: apps/web/.next)
// Values are never printed; a finding names the variable and the file only.

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";

const root = path.join(import.meta.dirname, "..");
const buildDir = path.resolve(process.argv[2] ?? path.join(root, "apps/web/.next"));

const SENSITIVE_NAME = /PASSWORD|SECRET|TOKEN|PRIVATE|CREDENTIAL|DATABASE_URL|_KEY$/;
const PUBLIC_PREFIX = "NEXT_PUBLIC_";
const MIN_VALUE_LENGTH = 8; // shorter values would match unrelated text
const SKIPPED_DIRECTORIES = new Set(["cache", "node_modules"]);

function sensitiveNeedles() {
  const needles = new Map(); // needle -> description
  for (const file of [".env", ".env.example"]) {
    const full = path.join(root, file);
    if (!existsSync(full)) continue;
    for (const [name, value] of Object.entries(parseEnv(readFileSync(full, "utf8")))) {
      if (name.startsWith(PUBLIC_PREFIX) || !SENSITIVE_NAME.test(name)) continue;
      needles.set(name, `the name ${name}`);
      if (value.length >= MIN_VALUE_LENGTH) needles.set(value, `the value of ${name} (${file})`);
    }
  }
  return needles;
}

function* walk(directory) {
  for (const entry of readdirSync(directory)) {
    const full = path.join(directory, entry);
    if (statSync(full).isDirectory()) {
      if (!SKIPPED_DIRECTORIES.has(entry)) yield* walk(full);
    } else {
      yield full;
    }
  }
}

if (!existsSync(buildDir)) {
  console.error(`check-web-bundle: ${buildDir} does not exist. Build the web app first.`);
  process.exit(2);
}

const needles = sensitiveNeedles();
if (needles.size === 0) {
  console.error("check-web-bundle: no sensitive variables found in .env or .env.example;");
  console.error("refusing to report success for a check that looked for nothing.");
  process.exit(2);
}

const findings = [];
let scanned = 0;
for (const file of walk(buildDir)) {
  scanned += 1;
  const content = readFileSync(file, "latin1");
  for (const [needle, description] of needles) {
    if (content.includes(needle)) {
      findings.push(`${path.relative(root, file)} contains ${description}`);
    }
  }
}

if (findings.length > 0) {
  console.error(`check-web-bundle: FAILED, ${findings.length} leak(s) in the web build:`);
  for (const finding of findings) console.error(`  - ${finding}`);
  process.exit(1);
}
console.log(
  `check-web-bundle: OK, ${scanned} files scanned for ${needles.size} sensitive names and values.`,
);
