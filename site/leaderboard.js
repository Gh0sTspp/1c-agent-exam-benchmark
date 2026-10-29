// One leaderboard table: accepted community results plus, on a local stand, this machine's own
// results highlighted with a send button. A row expands into violations and, locally, the agent log.
import {loadPenaltyMetadata, renderCharges} from './penalty-cards.js';
import {estimateApiCost, API_PRICES} from './api-cost.js';

const penaltyMetadata = await loadPenaltyMetadata();
const $ = id => document.getElementById(id);
const node = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
const number = v => String(v).replace('.', ',');
const grades = {unsatisfactory: 'Неудовлетворительно', satisfactory: 'Удовлетворительно', good: 'Хорошо', excellent: 'Отлично'};
const agents = {codex: 'Codex', claude: 'Claude Code'};
const tokens = n => n == null ? '—' : n >= 1e6 ? number((n / 1e6).toFixed(1)) + ' млн' : n >= 1e3 ? Math.round(n / 1e3) + ' тыс.' : String(n);
const periodNames = {Year: 'год', Quarter: 'квартал', Month: 'месяц', Day: 'день', Second: 'секунда', Nonperiodical: 'непериодический', RecorderPosition: 'позиция регистратора'};
const readableReason = text => String(text).replace(/периодичность регистра (policies|specification) — (\w+), ожидается (\w+)/g,
  (_, role, actual, expected) => `периодичность регистра ${role === 'policies' ? 'учётной политики' : 'состава'} — ${periodNames[actual] || actual}, ожидается ${periodNames[expected] || expected}`);
const minutes = s => s == null ? '—' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const harnessName = h => !h || h === 'none' ? 'Без харнеса' : h;
const systems = {Darwin: 'macOS', Windows: 'Windows', Linux: 'Linux'};
const arch = a => ({amd64: 'x64', x86_64: 'x64', arm64: 'arm64', aarch64: 'arm64'})[String(a).toLowerCase()] || a;
const isolation = {'dedicated-host': 'без песочницы', macos: 'песочница macOS', bubblewrap: 'песочница Linux'};
let rows = [], sort = {key: 'penalties', dir: 1}, local = null, submit = null;

export function fromCommunity(r) {
  const v = r.result, c = r.conditions || {}, m = r.measurement || {};
  return {id: r.id, local: false, model: v.model, agent: c.client || (String(v.model).startsWith('claude') ? 'claude' : 'codex'),
    agentVersion: c.client_version, effort: c.reasoning_effort, harness: v.harness, e: v, limit: c.solve_timeout_seconds,
    tokens: c.tokens || {}, tools: c.tools || {}, env: m.environment || {}, author: m.operator || {}, date: v.created_at,
    download: r.download, sha: r.archive_sha256, verification: r.verification, ownerVerification: r.owner_verification, sourceContext: r.source_context, regrade: r.regrade_required || [],
    runId: r.run_id || v.run_id || r.id, history: (r.previous_evaluations || []).map(fromCommunity)};
}

export function fromLocal(item) {
  const e = item.evaluation, run = item.run || {}, m = item.measurement || {};
  return {id: item.job_id, local: true, item, model: run.model || e.model, agent: run.client || 'codex', agentVersion: run.client_version,
    effort: run.reasoning_effort, harness: item.harness, e, limit: run.solve_timeout_seconds, tokens: run.tokens || {},
    tools: run.tools || {}, env: m.environment || {}, author: m.operator || {}, date: e.created_at,
    sourceContext: 'api/source-context?id=' + encodeURIComponent(item.job_id)};
}

// A score from an earlier grader, or one the current code cannot reproduce, stays visible but is not ranked.
const REGRADE = {grader_changed: r => 'Оценено прежней версией грейдера; изменились: ' + r.files.join(', ') + '.',
  adapter_not_in_repository: () => 'Привязки адаптированы кодом, которого нет в репозитории.',
  original_submission_refused: () => 'Исходная сдача агента не прошла приёмку; оценены привязки без доказательства адаптера.'};
const stale = r => (r.regrade || []).length > 0;
const exact = r => r.e.score != null && !r.e.infrastructure_errors && !stale(r);
const value = r => Number(exact(r) ? r.e.score : Math.max(0, r.e.score_upper_bound ?? 0));
const keys = {score: r => value(r) + (exact(r) ? 0.001 : 0), solve: r => r.e.solve_seconds, tokens: r => r.tokens.fresh_input ?? -1,
  date: r => Date.parse(r.date) || 0};

// Use the recorded deductions, never the clamped score or its upper bound.
export function penaltyPoints(e) {
  const parse = v => {
    if ((typeof v !== 'string' && typeof v !== 'number') || (typeof v === 'string' && !v.trim())) return null;
    const n = Number(v);
    return Number.isFinite(n) && n >= 0 ? n : null;
  };
  if (e?.deductions != null) return parse(e.deductions);
  if (!Array.isArray(e?.charges) || !e.charges.length) return null;
  const points = e.charges.map(c => parse(c?.points));
  return points.some(n => n == null) ? null : Number(points.reduce((a, b) => a + b, 0).toPrecision(12));
}

export function comparePenalties(a, b, direction = 1) {
  const x = penaltyPoints(a.e), y = penaltyPoints(b.e);
  if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
  return direction * (x - y);
}

export function penaltyLabel(e) {
  const n = penaltyPoints(e);
  if (n == null) return 'штрафные баллы: нет данных';
  const partial = e.infrastructure_errors || e.score == null || Number(e.not_assessed) > 0 || Number(e.counts?.inconclusive) > 0;
  return `штрафные баллы: ${number(n)}${partial ? ' · проверка неполная' : ''}`;
}

// The solve limit is distinct from actual execution time. Unknown is selectable, not zero.
export function limitKey(limit) {
  if (typeof limit === 'string' && !/^\d+$/.test(limit)) return 'unknown';
  if (typeof limit !== 'string' && typeof limit !== 'number') return 'unknown';
  const seconds = Number(limit);
  return Number.isSafeInteger(seconds) && seconds > 0 ? String(seconds) : 'unknown';
}

export function limitLabel(limit) {
  const key = limitKey(limit);
  if (key === 'unknown') return 'Не указан';
  const seconds = Number(key), minutes = Math.floor(seconds / 60), remainder = seconds % 60;
  return minutes ? `${minutes} мин${remainder ? ` ${remainder} сек` : ''}` : `${seconds} сек`;
}

export function limitOptions(values) {
  const keys = new Set(values.map(limitKey));
  const numeric = [...keys].filter(k => k !== 'unknown').sort((a, b) => Number(a) - Number(b));
  if (keys.has('unknown')) numeric.push('unknown');
  return numeric.map(value => ({value, label: limitLabel(value)}));
}

export function matchesLimit(limit, selection) {
  return !selection || limitKey(limit) === selection;
}

export function filtersMatch(r) {
  return ['agent', 'model', 'harness'].every(k => !$('f-' + k).value || String(r[k]) === $('f-' + k).value)
    && matchesLimit(r.limit, $('f-limit').value);
}

export function fillLimitFilter(values) {
  const select = $('f-limit'), current = select.value;
  const all = node('option', 'Все'); all.value = '';
  const options = limitOptions(values).map(({value, label}) => { const o = node('option', label); o.value = value; return o; });
  select.replaceChildren(all, ...options);
  if ([...select.options].some(o => o.value === current)) select.value = current;
}

function fillFilter(id, values, label) {
  const select = $(id), current = select.value;
  select.replaceChildren(node('option', 'Все'), ...[...new Set(values)].sort().map(v => { const o = node('option', label(v)); o.value = v; return o; }));
  select.firstChild.value = '';
  if ([...select.options].some(o => o.value === current)) select.value = current;
}

function sub(parent, text) { if (text) parent.append(node('small', text)); return parent; }

function revisionHistory(r) {
  const history = node('details', null, 'evaluation-history');
  history.append(node('summary', `Предыдущие оценки (${r.history.length})`),
    node('p', 'Это пересчёты одного прогона, а не дополнительные попытки агента. В таблице показана последняя оценка. Каждый пакет сохранён отдельно.', 'why'));
  for (const old of r.history) {
    const revision = node('details');
    const score = old.e.score != null ? `${number(old.e.score)} из 5` : `не выше ${number(Math.max(0, old.e.score_upper_bound ?? 0))} из 5`;
    revision.append(node('summary', `${old.date ? new Date(old.date).toLocaleString('ru-RU') : old.id} · ${score}`),
      node('p', old.id, 'why'), violations(old));
    const download = node('a', 'Скачать эту оценку и решение XML/DT', 'btn small');
    download.href = old.download; download.download = '';
    download.title = 'SHA-256 ' + old.sha;
    revision.append(download);
    history.append(revision);
  }
  return history;
}

function violations(r) {
  const box = node('div', null, 'details-grid');
  const charges = node('div', null, 'run-errors'); charges.append(node('h4', 'Штрафы'));
  if (r.e.charges?.length) {
    const list = node('ul');
    renderCharges(list, r.e.charges, penaltyMetadata, {methodology: Boolean(local), sourceContext: r.sourceContext});
    charges.append(list);
  } else charges.append(node('p', 'Нет', 'why'));
  const failed = node('div', null, 'run-failures'); failed.append(node('h4', 'Не пройденные требования'));
  const bad = (r.e.rules || []).filter(x => x.verdict === 'fail');
  if (bad.length) {
    const list = node('ul');
    list.append(...bad.map(x => node('li', x.id + (x.reason ? ' · ' + x.reason : ''))));
    failed.append(list);
  } else failed.append(node('p', 'Нет', 'why'));
  const notes = node('div', null, 'run-coverage'); notes.append(node('h4', 'Покрытие'));
  notes.append(node('p', `Проверок пройдено: ${r.e.counts?.pass || 0}, не пройдено: ${r.e.counts?.fail || 0}, `
    + `не определено: ${r.e.counts?.inconclusive || 0}. Пунктов каталога без оценки: ${r.e.not_assessed ?? '—'}.`, 'why'));
  if (stale(r)) notes.append(node('p', 'Требуется пересчёт, место не присваивается. ' + r.regrade.map(x => REGRADE[x.id]?.(x) || x.id).join(' '), 'why'));
  if (r.e.binding_compatibility) notes.append(node('p', 'Оценено с адаптацией привязок: исходная сдача не загрузилась без неё.', 'why'));
  if (r.tools?.mcp_calls != null) notes.append(node('p', `Вызовов MCP-инструментов: ${r.tools.mcp_calls}, с ошибкой: ${r.tools.failed_calls || 0}.`, 'why'));
  const verification = r.ownerVerification;
  if (verification) {
    const grader = verification.grader, server = verification.server, hw = server.hardware || {};
    const review = node('div', null, 'run-verification');
    review.append(node('h4', verification.outcome === 'incomplete' ? 'Неполная проверка владельца' : 'Проверено владельцем репозитория'));
    review.append(node('p', `@${verification.operator.github} · ${new Date(verification.completed_at).toLocaleString('ru-RU')}`));
    if (verification.method === 'saved_platform_observations') review.append(node('p', 'Оценка пересчитана по сохранённым наблюдениям 1С. Исходное решение повторно не запускалось.', 'why'));
    if (verification.outcome === 'incomplete') review.append(node('p', 'Часть сценариев не завершилась; оценка неполная.', 'why'));
    review.append(node('p', `Грейдер: ${grader.profile} · коммит ${grader.commit || 'не указан'}${grader.working_tree_dirty ? ' (с локальными изменениями)' : ''}`));
    review.append(node('p', 'SHA-256 грейдера: ' + grader.sha256, 'why'));
    review.append(node('p', `Сервер: ${server.name} · ${server.os.system} ${server.os.release || ''} · ${server.os.architecture || ''}`));
    review.append(node('p', [hw.cpu, hw.logical_cpus && hw.logical_cpus + ' потоков', hw.ram_bytes && Math.round(hw.ram_bytes / 1073741824) + ' ГБ RAM'].filter(Boolean).join(' · ')));
    review.append(node('p', `Платформа перепроверки: 1С ${verification.platform_version} · ${isolation[server.isolation] || server.isolation || ''}`));
    review.append(node('p', 'Условия исходного запуска агента сохранены в основной строке. Отметка подтверждает перепроверку, а не успешное решение всех требований.', 'why'));
    box.append(review);
  }
  box.append(charges, failed, notes);
  if (r.local) {
    const log = node('button', 'Открыть лог агента', 'btn small');
    log.addEventListener('click', () => showLog(r));
    box.append(log);
  }
  return box;
}

async function showLog(r) {
  const dialog = node('dialog', null, 'ask prompt-dialog log-dialog');
  const close = node('button', 'Закрыть', 'btn');
  close.addEventListener('click', () => { dialog.close(); dialog.remove(); });
  dialog.addEventListener('cancel', () => dialog.remove());
  const body = node('div', 'Загружаем…', 'log');
  dialog.append(node('h2', `Лог агента · ${r.model}`), body, close);
  document.body.append(dialog); dialog.showModal();
  try {
    const response = await fetch('api/results/log?id=' + encodeURIComponent(r.id), {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    body.replaceChildren(...data.steps.map(s => {
      if (s.kind === 'message') return node('p', s.text, 'log-message');
      const d = node('details', null, 'log-step');
      d.append(node('summary', (s.kind === 'command' ? '$ ' : '⚙ ') + s.text + (s.exit_code ? `  · код ${s.exit_code}` : '')));
      const out = [s.output, s.result].filter(Boolean).join('\n— ответ —\n');
      if (out) d.append(node('pre', out, 'review'));
      return d;
    }));
  } catch (error) { body.textContent = error.message || 'Лог недоступен'; }
}

function openRun(r) {
  const dialog = node('dialog', null, 'run-viewer');
  dialog.setAttribute('aria-label', 'Разбор решения 1С');
  const header = node('header', null, 'run-viewer-head');
  const heading = node('div');
  heading.append(node('p', 'РАЗБОР РЕШЕНИЯ', 'run-eyebrow'), node('h2', r.model || 'Экзамен 1С'));
  heading.append(node('p', [harnessName(r.harness), r.author.name || r.author.github,
    r.date && new Date(r.date).toLocaleDateString('ru-RU')].filter(Boolean).join(' · '), 'why'));
  const close = node('button', 'Закрыть ×', 'btn'); close.autofocus = true;
  close.addEventListener('click', () => dialog.close());
  header.append(heading, close);
  const metrics = node('div', null, 'run-metrics');
  const score = exact(r) ? `${number(r.e.score)} / 5` : `≤ ${number(Math.max(0, r.e.score_upper_bound ?? 0))} / 5`;
  for (const [value, label] of [[score, exact(r) ? 'оценка' : 'верхняя граница оценки'],
    [r.e.charges?.length || 0, 'начисленных штрафов'], [r.e.counts?.pass || 0, 'проверок пройдено']]) {
    const metric = node('div'); metric.append(node('strong', value), node('span', label)); metrics.append(metric);
  }
  const status = node('p', stale(r) ? 'Оценка ожидает пересчёта обновлённым грейдером.'
    : r.e.infrastructure_errors ? 'Часть сценариев не завершилась. Результат проверки неполный.'
    : r.ownerVerification?.method === 'saved_platform_observations' ? 'Пересчитано владельцем по сохранённым наблюдениям 1С.'
    : r.ownerVerification ? 'Перепроверено владельцем репозитория.'
    : 'Оценка предоставлена участником.', 'run-status');
  const layout = node('div', null, 'run-layout');
  const nav = node('nav', null, 'run-navigation'); nav.setAttribute('aria-label', 'Разделы разбора');
  const content = node('div', null, 'run-content');
  const details = violations(r);
  const errors = details.querySelector('.run-errors');
  errors.querySelector('h4').textContent = 'Ошибки в решении';
  const intro = node('p', 'Откройте карточку, чтобы увидеть код и обоснование.', 'run-intro');
  errors.insertBefore(intro, errors.children[1] || null);
  if (Array.isArray(r.e.observation_errors) && r.e.observation_errors.length) {
    const reasons = node('details');
    reasons.append(node('summary', 'Причины неполной проверки'));
    const list = node('ul');
    for (const problem of r.e.observation_errors) {
      if (problem && typeof problem.scenario === 'string' && typeof problem.reason === 'string')
        list.append(node('li', `${problem.scenario}: ${problem.reason}`));
    }
    if (list.children.length) { reasons.append(list); errors.insertBefore(reasons, intro.nextSibling); }
  }
  if (!r.e.charges?.length) errors.append(node('p', 'Штрафов не начислено. Это не подтверждает выполнение непроверенных требований.', 'why'));
  const checks = node('section'); checks.append(node('h3', 'Проверки билета'));
  const verdicts = {fail: ['Не пройдены', 'fail'], inconclusive: ['Недостаточно данных', 'unknown'], pass: ['Пройдены', 'pass']};
  for (const [verdict, [label, cls]] of Object.entries(verdicts)) {
    const items = (r.e.rules || []).filter(x => x.verdict === verdict);
    const group = node('details', null, 'run-check-group'); group.open = verdict === 'fail';
    group.append(node('summary', `${label} · ${items.length}`, cls));
    for (const item of items) {
      const line = node('p'); line.append(node('b', item.id), document.createTextNode(' · ' + readableReason(item.reason || penaltyMetadata.requirements?.[item.id]?.title || 'Подробности в протоколе проверки'))); group.append(line);
    }
    checks.append(group);
  }
  checks.append(node('p', `Пунктов каталога без оценки: ${r.e.not_assessed ?? '—'}. Непроверенные пункты не считаются выполненными.`, 'run-coverage'));
  if (r.e.binding_compatibility) checks.append(node('p', 'Для проверки потребовалась адаптация привязок объектов.', 'why'));
  const conditions = node('section'); conditions.append(node('h3', 'Как агент решал задачу'));
  const env = r.env || {}, hw = env.hardware || {};
  const list = node('dl', null, 'run-facts');
  for (const [label, value] of [['Модель', r.model], ['Агент', [agents[r.agent] || r.agent, r.agentVersion].filter(Boolean).join(' ')],
    ['Харнес', harnessName(r.harness)], ['Лимит решения', r.limit ? Math.round(r.limit / 60) + ' мин' : '—'],
    ['Время решения', minutes(r.e.solve_seconds)], ['Автор', r.author.name || r.author.github],
    ['Платформа исходного замера', env.platform_version && '1С ' + env.platform_version],
    ['Компьютер', [systems[env.os?.system] || env.os?.system, hw.cpu, hw.ram_bytes && Math.round(hw.ram_bytes / 1073741824) + ' ГБ RAM'].filter(Boolean).join(' · ')],
    ['Токены', `новый вход ${tokens(r.tokens.fresh_input)}, кешированный вход ${tokens(r.tokens.cached_input)}, выход ${tokens(r.tokens.output)}`],
    ...(API_PRICES[r.model]?.cacheWrite ? [['Запись кеша', tokens(r.tokens.cache_creation_input)]] : []),
    ['Оценка API', estimateApiCost(r.model, r.tokens) == null ? 'Нет данных для расчёта' : `≈ $${number(estimateApiCost(r.model, r.tokens).toFixed(2))} · условный расчёт`]]) {
    list.append(node('dt', label), node('dd', value || '—'));
  }
  conditions.append(list);
  const rate = API_PRICES[r.model];
  let explanation = 'Оценка по стандартным тарифам API на 27.10.2026. Это не счёт за подписку; длинный контекст, режим обработки и дополнительные услуги не учтены. ';
  if (rate?.cacheWrite) explanation += r.tokens.cache_creation_input == null
    ? 'Количество записанных в кеш токенов не сохранено: оценка не учитывает доплату за запись и может быть занижена. '
    : 'Запись кеша включена в новый вход и рассчитывается отдельно по тарифу на 5 минут; фактический срок хранения не подтверждён и может быть иным. ';
  if (r.model === 'grok-4.7-high') explanation += 'Для Grok High использован обычный тариф Grok 4.7, не Fast. ';
  const pricing = node('p', explanation, 'why');
  if (rate) {
    pricing.append(document.createTextNode(`Тариф за миллион токенов: вход $${rate.input}, чтение кеша $${rate.cached}, ${rate.cacheWrite ? `запись кеша (5 мин) $${rate.cacheWrite}, ` : ''}выход $${rate.output}. `));
    const pricingLink = node('a', `Тарифы ${rate.provider}`); pricingLink.href = rate.source; pricingLink.target = '_blank'; pricingLink.rel = 'noopener noreferrer'; pricing.append(pricingLink);
  }
  conditions.append(pricing);
  if (r.ownerVerification) conditions.append(node('p', `Перепроверка: @${r.ownerVerification.operator.github} · ${r.ownerVerification.server.name} · 1С ${r.ownerVerification.platform_version}.`, 'run-status'));
  const technical = node('section'); technical.append(node('h3', 'История и технические данные'), node('p', 'Архивы, контрольные суммы и происхождение оценки нужны для независимой проверки.', 'why'));
  if (r.download) { const a = node('a', 'Скачать решение XML / DT и оценку', 'btn'); a.href = r.download; a.download = ''; technical.append(a); }
  technical.append(node('p', 'Исходный прогон: ' + (r.runId || r.id), 'why'));
  if (r.sha) technical.append(node('pre', 'SHA-256 архива: ' + r.sha, 'review'));
  if (r.regrade?.length) technical.append(node('p', r.regrade.map(x => REGRADE[x.id]?.(x) || x.id).join(' '), 'why'));
  const verification = details.querySelector('.run-verification'); if (verification) technical.append(verification);
  if (r.history?.length) technical.append(revisionHistory(r));
  if (r.local) { const log = node('button', 'Лог агента', 'btn'); log.addEventListener('click', () => showLog(r)); technical.append(log); }
  const tabs = [['Ошибки в решении', errors, 'Ошибки'], ['Проверки билета', checks, 'Проверки'],
    ['Условия замера', conditions, 'Условия'], ['История и данные', technical, 'История']];
  const controls = [];
  function select(index) {
    tabs.forEach(([, panel], i) => { panel.hidden = i !== index; controls[i].setAttribute('aria-pressed', String(i === index)); });
    content.scrollTop = 0;
  }
  tabs.forEach(([label, panel, short], i) => {
    const button = node('button'); button.setAttribute('aria-label', label);
    button.append(node('span', label, 'run-tab-full'), node('span', short, 'run-tab-short'));
    button.addEventListener('click', () => select(i));
    controls.push(button); nav.append(button); panel.classList.add('run-panel'); content.append(panel);
  });
  select(0); layout.append(nav, content); dialog.append(header, metrics, status, layout);
  const previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
  dialog.addEventListener('close', () => { document.body.style.overflow = previousOverflow; dialog.remove(); }, {once: true});
  document.body.append(dialog); dialog.showModal();
}

function render() {
  const visible = rows.filter(filtersMatch).sort((a, b) => (sort.key === 'penalties'
    ? comparePenalties(a, b, sort.dir) : sort.dir * (keys[sort.key](a) - keys[sort.key](b))) || a.e.solve_seconds - b.e.solve_seconds);
  // Places count only accepted results with an exact score, in score order.
  const ranked = rows.filter(r => !r.local && exact(r)).sort((a, b) => value(b) - value(a) || a.e.solve_seconds - b.e.solve_seconds);
  const places = new Map(ranked.map((r, i) => [r.id, i + 1]));
  for (const th of document.querySelectorAll('.sort')) th.dataset.dir = th.dataset.key === sort.key ? (sort.dir > 0 ? 'asc' : 'desc') : '';
  $('rows').replaceChildren(...visible.flatMap(r => {
    const tr = node('tr', null, 'row-main' + (r.local ? ' mine' : ''));
    const place = node('td', r.local ? 'ваш' : places.has(r.id) ? String(places.get(r.id)) : '—', 'num place');
    const score = node('td');
    score.append(node('b', exact(r) ? `${number(r.e.score)} из 5` : `не выше ${number(Math.max(0, r.e.score_upper_bound))} из 5`, 'score-value'));
    sub(score, grades[r.e.grade]);
    if (stale(r)) { const b = node('span', 'требуется пересчёт', 'badge warn'); b.title = 'Оценка выполнена прежним грейдером; подробности внутри прогона.'; score.append(b); }
    sub(score, penaltyLabel(r.e));
    if (r.verification === 'repository_owner') {
      const verification = node('small', '✓ проверил владелец', 'mobile-verification');
      verification.title = 'Перепроверено владельцем репозитория';
      score.append(verification);
    } else if (r.verification === 'repository_owner_incomplete') {
      const verification = node('small', '⚠ проверка неполная', 'mobile-verification incomplete');
      verification.title = 'Часть сценариев не завершилась';
      score.append(verification);
    }
    const who = node('td'); who.append(node('b', r.model));
    sub(who, [agents[r.agent] || r.agent, r.agentVersion, r.effort].filter(Boolean).join(' · '));
    sub(who, harnessName(r.harness));
    const time = node('td', minutes(r.e.solve_seconds), 'num'); sub(time, limitKey(r.limit) === 'unknown' ? 'лимит не указан' : `лимит ${limitLabel(r.limit)}`);
    const estimate = estimateApiCost(r.model, r.tokens);
    const tok = node('td', null, 'num cost-cell');
    tok.append(node('b', estimate == null ? 'Нет расчёта' : `≈ $${number(estimate.toFixed(2))}`, 'cost-value'));
    sub(tok, `вход ${tokens(r.tokens.fresh_input)}`); sub(tok, `кеш ${tokens(r.tokens.cached_input)}`); sub(tok, `выход ${tokens(r.tokens.output)}`);
    if (API_PRICES[r.model]?.cacheWrite) sub(tok, r.tokens.cache_creation_input == null ? 'запись кеша неизвестна' : `запись ${tokens(r.tokens.cache_creation_input)}`);
    tok.title = 'Вход — новые токены (включая запись кеша); кеш — повторный вход. Расчёт записи Claude предполагает кеш на 5 минут. Стоимость приблизительная, не счёт за подписку. Подробности в условиях замера.';
    const env = r.env, hw = env.hardware || {};
    const pc = node('td', [systems[env.os?.system] || env.os?.system, env.os?.architecture && arch(env.os.architecture)].filter(Boolean).join(' ') || '—', 'pc');
    sub(pc, [hw.cpu, hw.logical_cpus && hw.logical_cpus + ' потоков', hw.ram_bytes && Math.round(hw.ram_bytes / 1073741824) + ' ГБ'].filter(Boolean).join(' · '));
    sub(pc, [env.platform_version && '1С ' + env.platform_version, isolation[env.isolation] || env.isolation].filter(Boolean).join(' · '));
    const author = node('td');
    if (r.author?.github) { const a = node('a', r.author.name || r.author.github); a.href = 'https://github.com/' + r.author.github; author.append(a); sub(author, '@' + r.author.github); }
    else author.append(node('span', r.author?.name || '—'));
    sub(author, r.date ? new Date(r.date).toLocaleDateString('ru-RU') : '');
    sub(author, r.local ? (r.item.publication?.state === 'published' ? 'опубликован' : r.item.publication?.state === 'submitted' ? 'PR создан' : 'локальный результат') : r.verification === 'repository_owner' ? 'проверено владельцем репозитория' : r.verification === 'repository_owner_incomplete' ? 'проверка владельца неполная' : r.verification === 'contributor_reported' ? 'заявлено участником' : r.verification);
    const cellActions = node('td'), act = node('div', null, 'row-actions');
    cellActions.append(act);
    if (r.local && submit) { const box = node('div', null, 'actions'); submit(box, r.item, local.community, local.githubReady, load); act.append(box); }
    else if (r.download) { const a = node('a', 'Скачать', 'btn small'); a.href = r.download; a.download = ''; a.title = 'Решение XML и DT, оценка, параметры · SHA-256 ' + r.sha; act.append(a); }
    const more = node('button', 'Открыть прогон', 'btn small row-more');
    more.addEventListener('click', () => openRun(r)); act.append(more);
    tr.append(place, score, who, time, tok, pc, author, cellActions);
    return [tr];
  }));
  const mine = visible.filter(r => r.local).length;
  $('summary').textContent = `${visible.length} из ${rows.length}` + (mine ? ` · локальных: ${mine}` : '');
  $('empty').hidden = visible.length > 0;
  $('empty').textContent = rows.length ? 'Нет результатов с такими условиями.' : 'Пока нет результатов. Сделайте замер и отправьте его в рейтинг.';
}

async function load() {
  let community = [];
  try {
    const response = await fetch('community.json', {cache: 'no-store'});
    if (response.ok) community = (await response.json()).results.map(fromCommunity);
  } catch { /* the table still shows local results */ }
  const sent = new Set(community.flatMap(r => [r.runId, r.id, ...r.history.map(old => old.id)]));
  let mine = [];
  try {
    const [results, state, readiness] = await Promise.all(['api/results', 'api/community', 'api/readiness']
      .map(u => fetch(u, {cache: 'no-store'}).then(r => { if (!r.ok) throw new Error(); return r.json(); })));
    if (!submit) ({renderSubmit: submit} = await import('./submit.js'));
    local = {community: state, githubReady: readiness.steps.find(s => s.id === 'github')?.state === 'ok'};
    mine = results.results.filter(i => i.evaluation && i.mode === 'run' && !sent.has(i.job_id)).map(fromLocal);
  } catch { local = null; }
  rows = [...community, ...mine];
  fillFilter('f-agent', rows.map(r => r.agent), v => agents[v] || v);
  fillFilter('f-model', rows.map(r => r.model), v => v);
  fillFilter('f-harness', rows.map(r => r.harness), harnessName);
  fillLimitFilter(rows.map(r => r.limit));
  render();
}

for (const id of ['f-agent', 'f-model', 'f-harness', 'f-limit']) $(id).addEventListener('change', render);
$('mobile-sort').addEventListener('change', () => {
  const key = $('mobile-sort').value;
  sort = {key, dir: key === 'solve' || key === 'tokens' || key === 'penalties' ? 1 : -1};
  render();
});
for (const th of document.querySelectorAll('.sort')) th.addEventListener('click', () => {
  sort = {key: th.dataset.key, dir: sort.key === th.dataset.key ? -sort.dir : (th.dataset.key === 'solve' || th.dataset.key === 'tokens' || th.dataset.key === 'penalties' ? 1 : -1)};
  $('mobile-sort').value = sort.key;
  render();
});
load();
