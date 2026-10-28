import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

// Exercise the page's actual filtering helpers without booting the server.
let source = await readFile(new URL('../site/leaderboard.js', import.meta.url), 'utf8');
source = source.replace("import {loadPenaltyMetadata, renderCharges} from './penalty-cards.js';", 'const loadPenaltyMetadata = async () => ({});');
source = source.replace("import {estimateApiCost, API_PRICES} from './api-cost.js';", 'const estimateApiCost = () => null, API_PRICES = {};');
source = source.replace(/\nload\(\);\s*$/, '\n');
const controls = Object.fromEntries(['agent', 'model', 'harness', 'limit'].map(k => ['f-' + k, {
  value: '', options: [], addEventListener() {},
  replaceChildren(...children) { this.options = children; this.value = children[0]?.value || ''; },
}]));
globalThis.document = {
  getElementById(id) { return controls[id] || {addEventListener() {}}; },
  querySelectorAll() { return []; },
  createElement(tag) { return {tag, value: '', textContent: ''}; },
};
const {limitKey, limitLabel, limitOptions, matchesLimit, filtersMatch, fillLimitFilter, fromCommunity, fromLocal} =
  await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

assert.equal(limitKey(null), 'unknown');
assert.equal(limitKey(undefined), 'unknown');
assert.equal(limitKey(0), 'unknown');
assert.equal(limitKey(-1), 'unknown');
assert.equal(limitKey(''), 'unknown');
assert.equal(limitKey(' 1800'), 'unknown');
assert.equal(limitKey(1800), '1800');
assert.equal(limitKey('1800'), '1800');
assert.equal(limitLabel(1800), '30 мин');
assert.equal(limitLabel(3630), '60 мин 30 сек');
assert.equal(limitLabel(45), '45 сек');
assert.equal(limitLabel(null), 'Не указан');
assert.deepEqual(limitOptions([7200, 1800, null, 3600, 7200, 450, 30, '3600']), [
  {value:'30',label:'30 сек'}, {value:'450',label:'7 мин 30 сек'}, {value:'1800',label:'30 мин'},
  {value:'3600',label:'60 мин'}, {value:'7200',label:'120 мин'}, {value:'unknown',label:'Не указан'},
]);
assert.equal(matchesLimit(null, ''), true);
assert.equal(matchesLimit(null, 'unknown'), true);
assert.equal(matchesLimit(1800, 'unknown'), false);
assert.equal(matchesLimit(1800, '1800'), true);
assert.equal(matchesLimit(3600, '1800'), false);

const local = fromLocal({job_id:'demo-a', evaluation:{}, run:{solve_timeout_seconds:3600}, measurement:{}});
const community = fromCommunity({id:'demo-b', result:{}, conditions:{solve_timeout_seconds:1800}});
assert.equal(local.limit, 3600);
assert.equal(community.limit, 1800);
controls['f-limit'].value = '1800';
assert.equal(filtersMatch(community), true);
assert.equal(filtersMatch(local), false);
controls['f-agent'].value = 'claude';
assert.equal(filtersMatch(community), false);
controls['f-agent'].value = '';
fillLimitFilter([1800, 3600, null]);
assert.equal(controls['f-limit'].value, '1800');
fillLimitFilter([3600, null]);
assert.equal(controls['f-limit'].value, '');
controls['f-limit'].value = 'unknown';
fillLimitFilter([1800, null]);
assert.equal(controls['f-limit'].value, 'unknown');

const html = await readFile(new URL('../site/leaderboard.html', import.meta.url), 'utf8');
assert.match(html, /Лимит решения<select id="f-limit"/);
const css = await readFile(new URL('../site/style.css', import.meta.url), 'utf8');
assert.match(css, /\.filters \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
assert.match(css, /\.filters \.mobile-sort \{ display: flex; grid-column: auto;/);
assert.match(css, /\.filters \.why \{ grid-column: auto;/);
