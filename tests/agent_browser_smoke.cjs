// Real local-browser review workflow. No provider requests or CAD execution.
// Usage: node tests/agent_browser_smoke.cjs --review REVIEW.html --out DIRECTORY
//        [--name blocked] [--select operator-choices.json] [--browser CHROMIUM]
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

async function main() {
  const args = {};
  for (let i = 2; i < process.argv.length; i += 2) {
    const key = process.argv[i];
    assert(['--review', '--out', '--name', '--select', '--browser'].includes(key), 'Unknown browser smoke argument');
    assert(process.argv[i + 1], 'Missing browser smoke argument');
    args[key.slice(2)] = process.argv[i + 1];
  }
  assert(args.review && args.out, '--review and --out are required');
  const review = path.resolve(args.review);
  const output = path.resolve(args.out);
  const name = args.name || 'review';
  assert(/^[a-z0-9_-]+$/.test(name), 'Invalid output name');
  assert(fs.statSync(review).isFile(), 'Review file missing');
  fs.mkdirSync(output, { recursive: true });
  const report = { review_file: review, browser: 'Chromium / Playwright',
    evidence_kind: 'actual_local_browser_workflow', provider_requests: 0,
    external_requests: [], console_errors: [], screenshots: [] };
  const browser = await chromium.launch({ headless: true,
    ...(args.browser ? { executablePath: path.resolve(args.browser) } : {}),
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  report.browser_version = browser.version();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1040 }, acceptDownloads: true });
  const page = await context.newPage();
  await page.route('**/*', route => {
    const url = route.request().url();
    if (/^(file|data|blob):/.test(url)) return route.continue();
    report.external_requests.push(url);
    return route.abort();
  });
  page.on('pageerror', error => report.console_errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.console_errors.push(message.text()); });
  try {
    await page.goto(pathToFileURL(review).href, { waitUntil: 'load' });
    await page.locator('img').evaluateAll(images => images.forEach(image => image.loading = 'eager'));
    await page.waitForFunction(() => [...document.images].every(image => image.complete && image.naturalWidth > 0));
    assert.match(await page.title(), /MarinaFrame/);
    assert.match(await page.locator('.status').innerText(), /Human semantic review required/);
    report.figure_count = await page.locator('figure').count();
    report.sections = await page.locator('fieldset[data-section]').evaluateAll(fields => fields.map(field => ({
      section_id: field.dataset.section,
      candidates: [...field.querySelectorAll('label.choice')].map(label => {
        const input = label.querySelector('input');
        return { candidate_id: input.value, label: label.innerText, disabled: input.disabled, checked: input.checked };
      }),
    })));
    report.measurements = JSON.parse(await page.locator('#measurements pre').innerText());
    async function screenshot(suffix, locator) {
      const target = path.join(output, `${name}-${suffix}.png`);
      if (locator) await locator.screenshot({ path: target });
      else await page.screenshot({ path: target, fullPage: true });
      report.screenshots.push(target);
    }
    await screenshot('desktop');
    await screenshot('evidence', page.locator('#evidence'));
    await screenshot('selection', page.locator('#selection'));
    if (args.select) {
      const choices = JSON.parse(fs.readFileSync(args.select, 'utf8'));
      assert(Array.isArray(choices) && choices.length > 0, 'Operator choices must be a nonempty list');
      if ((await page.locator('input[type=radio]:checked').count()) === 0) {
        await page.getByRole('button', { name: 'Download selection decision' }).click();
        assert.match(await page.locator('#selection-status').innerText(), /Select at least one inspected contour/);
        report.empty_selection_rejected = true;
      }
      for (const choice of choices) {
        assert(/^[A-Za-z0-9_.:-]+$/.test(choice.section_id) && /^[A-Za-z0-9_.:-]+$/.test(choice.candidate_id), 'Invalid choice identifier');
        const radio = page.locator(`input[type=radio][name="${choice.section_id}"][value="${choice.candidate_id}"]`);
        await radio.check();
      }
      await screenshot('operator-selected', page.locator('#selection'));
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByRole('button', { name: 'Download selection decision' }).click(),
      ]);
      report.download_filename = download.suggestedFilename();
      const destination = path.join(output, 'selection-decision.json');
      await download.saveAs(destination);
      report.download_path = destination;
      const decision = JSON.parse(fs.readFileSync(destination, 'utf8'));
      assert.deepEqual(Object.keys(decision).sort(), ['arguments', 'reason', 'tool']);
      assert.equal(decision.tool, 'select_contours');
      assert.deepEqual(decision.arguments.selections, choices);
      assert.match(await page.locator('#selection-status').innerText(), /downloaded/);
      report.selection_download_valid_json = true;
      report.operator_choices = choices;
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => window.scrollTo(0, 0));
    report.mobile_horizontal_overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    await screenshot('mobile');
    assert.equal(report.mobile_horizontal_overflow, false, 'Mobile review overflows horizontally');
    assert.equal(report.console_errors.length, 0, 'Browser logged errors');
    assert.equal(report.external_requests.length, 0, 'Offline review attempted external network access');
    report.passed = true;
  } catch (error) {
    report.passed = false;
    report.error = error.message;
    process.exitCode = 1;
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(output, `${name}-browser-report.json`), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report, null, 2));
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
