// Release UI staging (docs/plans/2026-11-09-packaging.md, step 2).
//
// `npm run build` (tauri build with src-tauri/tauri.release.conf.json) runs this first. It copies
// only the files the app needs from ui/ into ui-release/ (git-ignored), and the release build
// embeds ui-release/. The browser mock (ui/mock), the screenshots and any local data stay out.
//
// The build fails when a staged file has an extension outside ALLOWED_EXTENSIONS (drawings,
// CAD and model files such as .glb, .step, .tif or .pdf are never part of the UI) or is larger
// than MAX_FILE_BYTES. Run it alone: node scripts/stage-release-ui.mjs

import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

/** The top-level entries of ui/ that the app loads. Everything else stays out. */
export const INCLUDED = ['index.html', 'styles.css', 'js', 'vendor', 'assets'];
/** Text and font types of a web UI. A file without an extension is a licence text (LICENSE). */
export const ALLOWED_EXTENSIONS = new Set(['.html', '.css', '.js', '.mjs', '.svg', '.woff2', '.txt', '.md', '']);
/** The largest UI file today is the three.js module (0.7 MB); a drawing or a model is larger. */
export const MAX_FILE_BYTES = 1024 * 1024;

function filesUnder(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isSymbolicLink()) return [path]; // reported as a problem below
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

/** Every reason the staged folder may not ship, one line per file; empty when it may. */
export function problems(folder) {
  return filesUnder(folder).flatMap((path) => {
    const name = relative(folder, path);
    const stats = statSync(path, { throwIfNoEntry: false });
    if (!stats || !stats.isFile()) return [`${name}: not a regular file`];
    const found = [];
    const extension = extname(path).toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(extension)) found.push(`${name}: ${extension} files are not part of the UI (drawing, model or data file?)`);
    if (stats.size > MAX_FILE_BYTES) found.push(`${name}: ${stats.size} bytes, more than ${MAX_FILE_BYTES}`);
    return found;
  });
}

/** Copy the included entries of `source` into a fresh `target` and check the result. */
export function stage(source, target) {
  rmSync(target, { recursive: true, force: true });
  mkdirSync(target, { recursive: true });
  for (const entry of INCLUDED) {
    const from = join(source, entry);
    if (!existsSync(from)) throw new Error(`ui/${entry} is missing`);
    cpSync(from, join(target, entry), { recursive: true, dereference: false, verbatimSymlinks: true });
  }
  return problems(target);
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const app = join(dirname(fileURLToPath(import.meta.url)), '..');
  const found = stage(join(app, 'ui'), join(app, 'ui-release'));
  if (found.length) {
    console.error(`Release UI check failed:\n  ${found.join('\n  ')}`);
    process.exit(1);
  }
  console.log(`Release UI staged in ui-release/ (${filesUnder(join(app, 'ui-release')).length} files, no mock or local data).`);
}
