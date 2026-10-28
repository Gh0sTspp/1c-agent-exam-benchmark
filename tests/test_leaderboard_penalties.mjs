import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

// Load the actual leaderboard helpers without booting the page or making network calls.
let source = await readFile(new URL('../site/leaderboard.js', import.meta.url), 'utf8');
source = source.replace("import {loadPenaltyMetadata, renderCharges} from './penalty-cards.js';", 'const loadPenaltyMetadata = async () => ({});');
source = source.replace("import {estimateApiCost, API_PRICES} from './api-cost.js';", 'const estimateApiCost = () => null, API_PRICES = {};');
source = source.replace(/\nload\(\);\s*$/, '\n');
globalThis.document = {getElementById: () => ({addEventListener() {}}), querySelectorAll: () => []};
const {penaltyPoints, penaltyLabel, comparePenalties} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));

assert.equal(penaltyPoints({deductions: '10.25', score_upper_bound: 0}), 10.25);
assert.equal(penaltyPoints({deductions: 0, charges: []}), 0);
assert.equal(penaltyPoints({charges: [{points: '0.1'}, {points: '0.2'}]}), 0.3);
assert.equal(penaltyPoints({}), null);
assert.equal(penaltyPoints({deductions: '', charges: [{points: '2'}]}), null);
assert.equal(penaltyPoints({charges: [{points: '1'}, {}]}), null);
assert.equal(penaltyPoints({deductions: -1}), null);
assert.equal(penaltyLabel({deductions: '2.5', score: null}), 'штрафные баллы: 2,5 · проверка неполная');
assert.equal(penaltyLabel({deductions: '0', score: 5}), 'штрафные баллы: 0');
assert.equal(penaltyLabel({}), 'штрафные баллы: нет данных');

const rows = [{e: {deductions: '20', score_upper_bound: 0}}, {e: {}},
  {e: {deductions: '6', score_upper_bound: 0}}, {e: {deductions: '0', score: 5}}];
assert.deepEqual([...rows].sort((a, b) => comparePenalties(a, b)).map(r => penaltyPoints(r.e)), [0, 6, 20, null]);
assert.deepEqual([...rows].sort((a, b) => comparePenalties(a, b, -1)).map(r => penaltyPoints(r.e)), [20, 6, 0, null]);
