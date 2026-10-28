import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = (await readFile(new URL('../site/submit.js', import.meta.url), 'utf8'))
  .replace("import {node, post} from './local.js';", 'const {node, post} = globalThis.__submissionTest;');
function node(tag, text, cls) {
  return {tag, textContent: text ?? '', className: cls, children: [],
    addEventListener() {}, append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; }};
}
globalThis.__submissionTest = {node, post: async () => {}};
const {renderSubmit} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const pr = 'https://github.com/zeegin/1c-agent-exam-benchmark/pull/123';
function show(item, community = {}, ready = true) {
  const box = node('div'); renderSubmit(box, {job_id: 'run', ...item}, community, ready, () => {}); return box.children;
}
const texts = children => children.map(c => c.textContent);
const noSend = children => assert.ok(!children.some(c => c.tag === 'button' && /Отправить/.test(c.textContent)));

let result = show({publication: {state: 'published', blocked: true}});
assert.ok(texts(result).includes('Опубликовано в рейтинге')); noSend(result);
assert.ok(result.some(c => c.tag === 'a' && c.href === 'leaderboard.html'));
result = show({publication: {state: 'published', blocked: true, url: pr}, pr_url: pr});
assert.ok(texts(result).includes('Опубликовано в рейтинге')); noSend(result);
assert.ok(result.some(c => c.href === pr));
result = show({publication: {state: 'submitted', blocked: true, url: pr}, prepared: true});
assert.ok(texts(result).includes('PR создан')); noSend(result);
result = show({publication: {state: 'closed', blocked: true, url: pr}, prepared: true});
assert.ok(texts(result).includes('PR закрыт')); noSend(result);
result = show({publication: {state: 'unknown', blocked: true, url: pr}, prepared: true}, {}, false);
assert.ok(texts(result).includes('Статус PR пока не подтверждён')); noSend(result);
assert.ok(!texts(result).some(x => x.includes('Нужен вход')));
result = show({publication: {state: 'unknown', blocked: true}}, {}, false);
assert.ok(texts(result).includes('Статус отправки пока не подтверждён')); noSend(result);
assert.ok(!texts(result).some(x => x.includes('PR')));
result = show({publication: {state: 'unknown', blocked: false}});
assert.ok(texts(result).includes('Отправить в рейтинг'));
result = show({publication: {state: 'unknown', blocked: false}, prepared: true});
assert.ok(texts(result).includes('Отправить PR'));
result = show({pr_url: pr}); assert.ok(texts(result).includes('PR создан')); noSend(result);
result = show({publication: {state: 'published', blocked: true, url: 'https://malicious.example/'}}, {}, false);
assert.ok(texts(result).includes('Опубликовано в рейтинге')); noSend(result);
assert.ok(!result.some(c => c.href === 'https://malicious.example/'));
result = show({publication: {state: 'unknown', blocked: false}}, {action: {id: 'run', action: 'pr', phase: 'finished', pr_url: pr}});
assert.ok(texts(result).includes('PR создан')); noSend(result);
result = show({publication: {state: 'published', blocked: true}}, {action: {id: 'run', action: 'pr', phase: 'finished', pr_url: pr}});
assert.ok(texts(result).includes('Опубликовано в рейтинге')); noSend(result);
