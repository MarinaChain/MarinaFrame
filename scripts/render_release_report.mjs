/** Render the release Markdown using a supplied marked 17.0.5 module.
 * The resulting HTML has embedded figures, no scripts and no external assets.
 * This is optional report tooling, not a reconstruction runtime dependency.
 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [inputName, outputName, repositoryName, markedModule] = process.argv.slice(2);
if (!inputName || !outputName || !repositoryName || !markedModule) {
  throw new Error('Usage: node render_release_report.mjs INPUT.md OUTPUT.html REPOSITORY MARKED_ESM_MODULE');
}
const { marked } = await import(pathToFileURL(path.resolve(markedModule)).href);
const input = fs.realpathSync(inputName), repository = fs.realpathSync(repositoryName);
const markdown = fs.readFileSync(input, 'utf8');
const embedded = [];
function localPath(reference, {mustExist = false} = {}) {
  if (/^[a-z][a-z0-9+.-]*:/i.test(reference) || reference.startsWith('//')) {
    throw new Error('Unsupported local reference scheme');
  }
  const file = path.resolve(path.dirname(input), reference);
  const relative = path.relative(repository, file);
  if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new Error('Reference outside repository');
  }
  let cursor = repository;
  for (const part of relative.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, part);
    if (fs.existsSync(cursor) && fs.lstatSync(cursor).isSymbolicLink()) {
      throw new Error('Symlink in report reference');
    }
  }
  if (mustExist) {
    const real = fs.realpathSync(file), realRelative = path.relative(repository, real);
    if (realRelative === '..' || realRelative.startsWith(`..${path.sep}`) || path.isAbsolute(realRelative)) {
      throw new Error('Resolved figure outside repository');
    }
    if (!fs.statSync(real).isFile()) throw new Error('Figure must be an ordinary file');
  }
  return {file, relative: relative.split(path.sep).join('/')};
}
const tokens = marked.lexer(markdown, {gfm: true});
marked.walkTokens(tokens, token => {
  if (token.type === 'html' && !/^(?:\s*<!--[\s\S]*?-->\s*)+$/.test(token.raw)) {
    throw new Error('Raw HTML is not supported in release reports');
  }
  if (token.type === 'link') {
    if (/^https?:\/\//i.test(token.href) || token.href.startsWith('#')) return;
    const {relative} = localPath(token.href);
    token.href = `MarinaFrame-0.4/${relative}`;
  }
  if (token.type !== 'image') return;
  const {file, relative} = localPath(token.href, {mustExist: true});
  const raw = fs.readFileSync(file);
  if (raw.length > 16 * 1024 * 1024) throw new Error('Report figure is too large');
  const mime = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.svg':'image/svg+xml'}[path.extname(file)];
  if (!mime) throw new Error('Unsupported report figure');
  if (mime === 'image/svg+xml') throw new Error('Raster figures only; active SVG is not supported');
  embedded.push(relative);
  token.href = `data:${mime};base64,${raw.toString('base64')}`;
});
let body = marked.parser(tokens, {gfm: true});
if (/<script\b|<iframe\b|<object\b|<embed\b|<link\b|<audio\b|<video\b|<source\b|\ssrcset\s*=/i.test(body)) {
  throw new Error('Unsupported active or external asset in rendered body');
}
for (const match of body.matchAll(/<img\b[^>]*\bsrc="([^"]*)"[^>]*>/gi)) {
  if (!/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(match[1])) {
    throw new Error('Rendered figure is not a supported embedded raster');
  }
}
const sections = [];
body = body.replace(/<h2>(.*?)<\/h2>/g, (_whole, text) => {
  const plain = text.replace(/<[^>]*>/g, '');
  const id = `section-${sections.length + 1}`;
  sections.push({id, plain});
  return `<h2 id="${id}">${text}</h2>`;
});
body = body.replace(/<table>/g, '<div class="table-scroll"><table>').replace(/<\/table>/g, '</table></div>');
const title = (markdown.match(/^#\s+(.+)$/m)?.[1] || 'MarinaFrame 0.4').replace(/[<>&"]/g, '');
const toc = sections.map(x => `<li><a href="#${x.id}">${x.plain}</a></li>`).join('');
const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'">
<title>${title}</title><style>
:root{color-scheme:light;--ink:#172b3a;--muted:#536775;--accent:#006779;--line:#d9e2e7;--paper:#fff;--wash:#f4f7f9}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:17px/1.62 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.top{background:#102f42;color:white;padding:32px max(24px,calc((100vw - 1120px)/2));border-bottom:6px solid #15869b}.top b{letter-spacing:.13em;font-size:13px}.top p{margin:8px 0 0;color:#c8dce6;font-size:15px}
main{max-width:1180px;margin:28px auto 60px;padding:42px 48px;background:var(--paper);border:1px solid var(--line);border-radius:10px}
h1{font-size:38px;line-height:1.18;letter-spacing:-.025em;margin:0 0 24px}h2{font-size:26px;line-height:1.3;margin:48px 0 18px;padding-top:18px;border-top:2px solid var(--line);scroll-margin-top:16px}h3{font-size:21px;margin:32px 0 12px}
p{margin:14px 0}a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}strong{font-weight:680}li{margin:7px 0}nav{padding:20px 25px;background:var(--wash);border:1px solid var(--line);border-radius:8px;margin:28px 0}nav summary{font-weight:650;cursor:pointer}nav ol{columns:2;column-gap:28px;padding-left:22px;font-size:14px}nav li{break-inside:avoid;margin:7px 0}
.table-scroll{overflow:auto;margin:24px 0;border:1px solid var(--line);border-radius:7px}table{border-collapse:collapse;min-width:620px;width:100%;font-size:14px;line-height:1.5}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#edf3f6;font-weight:680}tr:last-child td{border-bottom:0}tr:nth-child(even) td{background:#fafcfd}
code{font: .87em/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;background:#edf2f5;padding:.12em .3em;border-radius:3px;overflow-wrap:anywhere}pre{padding:20px;background:#102b3c;color:#e2edf4;border-radius:7px;overflow:auto;font-size:14px}pre code{background:none;padding:0;color:inherit;overflow-wrap:normal}img{display:block;max-width:100%;height:auto;margin:24px auto;border:1px solid var(--line);border-radius:5px}blockquote{border-left:4px solid #15869b;margin-left:0;padding:8px 20px;background:var(--wash)}footer{font-size:13px;color:var(--muted);margin-top:42px;padding-top:20px;border-top:1px solid var(--line)}
@media(max-width:720px){body{font-size:16px}main{margin:0;border:0;border-radius:0;padding:28px 18px}h1{font-size:30px}h2{font-size:23px}nav ol{columns:1}.top{padding:24px 18px}}
@media print{body{background:white;font-size:10.5pt}main{max-width:none;margin:0;padding:0;border:0}.top,nav{display:none}h1{font-size:24pt}h2{font-size:16pt;break-after:avoid}h3{break-after:avoid}.table-scroll{overflow:visible}table{min-width:0;font-size:9pt}tr,img,pre{break-inside:avoid}a{color:inherit}pre{white-space:pre-wrap}footer{font-size:9pt}}
</style></head><body><header class="top"><b>MARINAFRAME / RESEARCH RELEASE 0.4</b><p>Rust control plane · retained native CAD engine · measured evidence · human engineering review required</p></header><main>
<nav aria-label="Report contents"><details><summary>Report contents</summary><ol>${toc}</ol></details></nav>
${body}
<footer>This file is self-contained for reading and figures. Relative evidence links resolve after extracting the source-and-evidence archive beside this file into <code>MarinaFrame-0.4/</code>. It contains no executable scripts or externally loaded assets. The associated archive manifest records source, runtime, evidence and history identities. Engineering approval remains false.</footer>
</main></body></html>\n`;
fs.mkdirSync(path.dirname(path.resolve(outputName)), {recursive:true});
fs.writeFileSync(outputName, html);
process.stdout.write(JSON.stringify({input:path.basename(input),output:path.basename(outputName),bytes:Buffer.byteLength(html),embedded_figures:embedded,sections:sections.length,renderer:'marked17.0.5',scripts:false,external_assets:false})+'\n');
