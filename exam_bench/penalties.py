"""Penalties of the official 1C list found in a graded submission, and the score they imply.

Two sources of proof:
- requirement verdicts the stand already observed in real 1C (a whole section failed, a single requirement failed,
  a declared report gives wrong results, no demo data);
- concrete signs in the exported metadata (lock mode, register kind, removed starter accounts, schedule link of
  calculation registers, duplicated invoices between sections, own document types).

Every rule of the list gets a status: violation, no_violation_found (a sign was looked for and not found) or
not_assessed. Charges follow the owner policy v4 (minimum penalty, one defect one penalty), see assessment.score_bound.
"""
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from .assessment import score_bound
from .codescan import lex, posting_modules, scan, unloaded_once
from . import queries, queryschema
from .bp import business_processes, recalculations
from .calcwrite import base_before_write, rewrites
from .examiner import course as course_signs, signs as examiner_signs, standards as standard_signs
from .gates import configuration_identity

SECTIONS = {'OU': 'F1C-OU01', 'BU': 'F1C-BU01', 'PR': 'F1C-PR01', 'F': 'F1C-UI01'}
CORE = ('OU', 'BU', 'PR')
REPORT_REQUIREMENTS = {'BU16': 'bu_sales', 'BU17': 'bu_sales', 'OU19': 'ou_statement', 'OU20': 'ou_statement', 'OU21': 'ou_sales', 'PR19': 'pr_bonus'}
MECHANISM_REQUIREMENTS = ('OU04', 'F03', 'PR14')
# A failed requirement proves these official items: the requirement tests exactly what the item forbids.
REQUIREMENT_PENALTIES = {
    'BU10': ('F1C-GEN09',), 'BU07': ('F1C-BU04', 'F1C-GEN11'), 'BU14': ('F1C-BU04', 'F1C-GEN11'), 'BU15': ('F1C-BU04', 'F1C-GEN11'),
    'OU15': ('F1C-GEN10',), 'OU16': ('F1C-GEN10',), 'OU17': ('F1C-GEN10',), 'OU13': ('F1C-GEN10',), 'BU13': ('F1C-GEN10',),
    'OU11': ('F1C-GEN11',), 'OU12': ('F1C-GEN16',), 'PR06': ('F1C-GEN16',),
    'PR13': ('F1C-PR15', 'F1C-GEN18'), 'PR10': ('F1C-PR03',), 'PR07': ('F1C-PR07',),
}
# Owner decision A24: practices of the examiner (examiner.json) and of the course (chistov.json) are charged under these
# ATT83PL items; the standards practice STD01 stays unscored.
PRACTICE_PENALTIES = {'EXM01': 'F1C-GEN28', 'EXM02': 'F1C-GEN21', 'EXM03': 'F1C-GEN22', 'EXM04': 'F1C-GEN12', 'EXM05': 'F1C-GEN01',
                      'CHS01': 'F1C-GEN12', 'CHS02': 'F1C-GEN10', 'CHS03': 'F1C-GEN01'}
BINDING_DOCUMENTS = (('objects', 'receipt'), ('objects', 'sale'), ('objects', 'manual'), ('ou', 'assembly'), ('pr', 'accrual'))
SECTION_BINDING = {'OU': 'ou', 'PR': 'pr', 'F': 'forms'}  # accounting bindings are the base contract, always present
# Document kinds the ticket names (Б2.1.2, Б3.1.1, Б3.5, Б4.10.1): not «own» documents in the sense of М4.33.
TICKET_DOCUMENTS = ('Приходная накладная', 'Расходная накладная', 'Сборка', 'Операция', 'Начисление зарплаты')


def read(path):
    return Path(path).read_text(encoding='utf-8-sig') if Path(path).is_file() else ''


def prop(text, name):
    m = re.search(r'<' + name + r'>([^<]*)</' + name + '>', text)
    return m.group(1) if m else None


def object_xml(src, ref):
    kind, name = ref.split('.', 1)
    folder = {'Document': 'Documents', 'Catalog': 'Catalogs', 'AccumulationRegister': 'AccumulationRegisters', 'InformationRegister': 'InformationRegisters',
              'AccountingRegister': 'AccountingRegisters', 'CalculationRegister': 'CalculationRegisters', 'ChartOfAccounts': 'ChartsOfAccounts',
              'ChartOfCalculationTypes': 'ChartsOfCalculationTypes'}[kind]
    return read(Path(src) / folder / (name + '.xml'))


def declared(binding, section, role):
    if section == 'objects':
        return (binding.get('objects') or {}).get(role)
    return ((binding.get(section) or {}).get('objects') or {}).get(role)


def lock_signs(src):
    """(unlocked, late): managed locks of the balances posting reads (#std460, #std661).

    A read of a register's balances needs an explicit lock unless the register's movements were written before it in
    the posting flow — then the write already locks them (the new posting method, #std661). A lock is
    БлокировкаДанных.Добавить("Регистр…"), Движения.<Имя>.БлокироватьДляИзменения = Истина, or a helper that passes its
    parameter to Добавить and is called with the register name. unlocked — registers read before their write and
    locked nowhere; late — reads that come before the Заблокировать() of a lock for that register in the same method.
    """
    from .calcwrite import entered_after_write, methods, writes
    table = {n: [d for d in defs if d[0].parts[-4] in ('Documents', 'CommonModules')] for n, defs in methods(src).items()}
    table = {n: defs for n, defs in table.items() if defs}
    scoped = {d[0] for defs in table.values() for d in defs}
    for path in posting_modules(src):
        if path not in scoped:
            code = lex(read(path))[0]
            table['__module__.' + path.relative_to(src).as_posix()] = [(path, code, 0, code)]
    after = entered_after_write(table)
    texts = [read(f) for f in sorted(src.rglob('*.bsl')) if 'BenchmarkObserver' not in f.parts]
    helpers = set()
    for text in texts:
        for m in re.finditer(r'(?:Процедура|Функция)\s+(\w+)\s*\(([^)]*)\)(.*?)(?:КонецПроцедуры|КонецФункции)', lex(text)[0], re.S):
            params = [p.strip().split('=')[0].replace('Знач ', '').strip() for p in m.group(2).split(',')]
            if any(re.search(r'\.Добавить\(\s*' + re.escape(p) + r'\s*\)', m.group(3)) for p in params if p):
                helpers.add(m.group(1))
    lock_call = r'(?:\.Добавить|' + '|'.join(map(re.escape, sorted(helpers))) + r')\(\s*"(РегистрНакопления|РегистрБухгалтерии)\.(\w+)"' if helpers else r'\.Добавить\(\s*"(РегистрНакопления|РегистрБухгалтерии)\.(\w+)"'
    locked = set()
    for text in texts:
        locked |= {m.group(2) for m in re.finditer(lock_call, text)}
        locked |= set(re.findall(r'Движения\.(\w+)\.БлокироватьДляИзменения\s*=\s*Истина', lex(text)[0]))
    unlocked, late = set(), []
    for name, defs in table.items():
        for path, code, start, body in defs:
            raw = path.read_text(encoding='utf-8-sig', errors='replace')[start:start + len(body)]
            written = []
            for w in writes(body):
                target = w.group(1)
                if target.split('.')[-1] == 'Движения':
                    written.append((w.start(), None))
                elif 'Движения.' in target:
                    written.append((w.start(), target.split('.')[-1]))
                else:
                    a = re.findall(r'(?<![\wЁё.])' + re.escape(target) + r'\s*=\s*[^;]*?Движения\.(\w+)', body[:w.start()])
                    written.append((w.start(), a[-1] if a else None))
            locks_here = []
            for m in re.finditer(lock_call, raw):
                done = re.search(r'\.Заблокировать\s*\(', raw[m.end():])
                locks_here.append((m.group(2), m.end() + done.start() if done and m.group(0).startswith('.') else m.start()))
            for m in re.finditer(r'(РегистрНакопления|РегистрБухгалтерии)\.(\w+)\.(?:Остатки|ОстаткиИОбороты)\s*\(', raw):
                reg, pos = m.group(2), m.start()
                if name in after or any(at < pos and (r is None or r == reg) for at, r in written):
                    continue  # read after the movements are written: the write locks them (#std661)
                if reg not in locked:
                    unlocked.add(reg)
                elif any(r == reg and at > pos for r, at in locks_here) and not any(r == reg and at < pos for r, at in locks_here):
                    late.append('%s:%d %s' % (path.relative_to(src), code.count('\n', 0, start + pos) + 1, reg))
    return sorted(unlocked), late


def signature(error):
    """Where an error happened in the solution's code and what it says, without observer frames and positions."""
    frames = [m for m in re.finditer(r'\{([^{}()]+\.[^{}()]+\((\d+)\))\}', error) if 'BenchmarkObserver' not in m.group(1)]
    if not frames:
        return None
    last = frames[-1]
    message = re.sub(r'\{\(\d+, ?\d+\)\}:?\s*', '', error[last.end():]).strip(' :').splitlines()[0][:200]
    return last.group(1) + ': ' + message


def case_errors(observation):
    """Error texts a case recorded: top-level *_error fields (accounting cases) and the errors map (section cases)."""
    out = [v for k, v in observation.items() if k.endswith('_error') and isinstance(v, str) and v not in ('', 'not_declared')]
    out += [v for v in (observation.get('errors') or {}).values() if isinstance(v, str) and v != 'not_declared']
    return out


def new_rows(observation):
    """Ledger rows a case's document added: its after-snapshot minus its before-snapshot, as a multiset."""
    key = lambda r: tuple(sorted((k, str(v)) for k, v in r.items()))
    left = Counter(key(r) for r in observation.get('before') or [])
    out = []
    for r in observation.get('after') or []:
        if left[key(r)]:
            left[key(r)] -= 1
        else:
            out.append(r)
    return out


def assess(rules, src, binding, requirements, starter, catalogue, policy, gates=None, observations=None):
    """rules: requirement verdicts from the grader; requirements: the ticket's requirement list (id, section, stand cases)."""
    src = Path(src)
    gates = gates or {}
    observations = observations or {}
    verdict = {r['id']: r for r in rules}
    section_of = {r['id']: r['section'] for r in requirements}
    cases_of = {r['id']: r['stand'].get('grader_cases') or [] for r in requirements}

    def root_cause(rid):
        """One error of the solution's code that every case of a failed requirement hit, or None."""
        common = None
        for case in cases_of.get(rid) or []:
            found = {sig for e in case_errors(observations.get(case) or {}) if (sig := signature(e))}
            common = found if common is None else common & found
            if not common:
                return None
        return sorted(common)[0] if common else None
    findings, status = [], {}

    def find(penalty, defect, why, evidence=None):
        findings.append({'penalty_id': penalty, 'defect_id': defect, 'reason': why, 'evidence': evidence or [],
                         'proof_kind': 'query_parse' if defect.startswith('code.query.') else 'query_schema' if defect.startswith('query.') else 'code_sign' if defect.startswith('practice.') or defect in ('code.loop_reads', 'code.virtual_parameters', 'code.registrar_fields', 'code.order_by_date', 'pr.schedule_table', 'pr.base_main_table', 'pr.base_before_write') else 'runtime_error' if defect.startswith('code.') else 'requirement_verdict' if defect.startswith(('section.', 'requirement.', 'report.')) else 'static_metadata'})
        status[penalty] = {'status': 'violation', 'reason': why}

    def clean(penalty, why):
        status.setdefault(penalty, {'status': 'no_violation_found', 'reason': why})

    # Batch 1: from requirement verdicts.
    attestation = []
    for section, penalty in SECTIONS.items():
        ids = [i for i, s in section_of.items() if s == section]
        got = [verdict[i] for i in ids if i in verdict]
        if not got or (SECTION_BINDING.get(section) and not binding.get(SECTION_BINDING[section])):
            status[penalty] = {'status': 'not_assessed', 'reason': 'раздел не объявлен в привязках: отсутствие не доказано (A04)'}
            if section in CORE:
                attestation.append(('not_attested', section))
            continue
        failed = [r for r in got if r['verdict'] == 'fail']
        judged = [r for r in got if r['verdict'] in ('pass', 'fail')]
        if judged and len(failed) == len(judged):
            find(penalty, 'section.' + section, 'все требования раздела не выполнены')
            if section in CORE:
                attestation.append(('not_passed', section))
            continue
        clean(penalty, 'раздел есть: часть требований выполнена')
        causes = {}
        for r in failed:
            cause = root_cause(r['id'])
            if cause:
                causes.setdefault(cause, []).append(r['id'])
                continue
            # A wrong report value proves a failed ticket requirement, not that the report's *form* differs from
            # the ticket (М4.3). The latter needs independent evidence of its columns, grouping or layout.
            why = 'не выполнено требование: ' + r['id'] + (' — ' + r['reason'] if r.get('reason') else '')
            find('F1C-GEN01', 'requirement.' + r['id'], why)
            # The same defect also proves the specific items; the charge stays the smallest applicable (A02, v4).
            for penalty in REQUIREMENT_PENALTIES.get(r['id'], ()):
                find(penalty, 'requirement.' + r['id'], why)
        # One error in the solution's code that breaks several requirements is one defect (A02: tests are not a multiplier).
        for cause, ids in causes.items():
            find('F1C-GEN12', 'code.' + cause, 'ошибка выполнения в коде решения ломает требования ' + ', '.join(ids) + ': ' + cause)
    # М4.12: the platform parses every complete query text of the solution in its infobase (nothing is executed).
    if queries.CASE in observations:
        checked, skipped = queries.verdicts(src, observations[queries.CASE])
        runtime = [f['reason'] for f in findings if f['penalty_id'] == 'F1C-GEN12']
        bad = [q for q in checked if q['status'] == 'error']
        for q in bad:
            text, owner = queries.message(q['error']), q['file'].split('/')[1]
            if text and any(text in r and owner in r for r in runtime):
                continue  # a failing scenario already proved this defect: same message from the same object (A02)
            find('F1C-GEN12', 'code.query.%s:%d' % (q['file'], q['line']), 'текст запроса не разбирается платформой: %s:%d — %s' % (q['file'], q['line'], text),
                 [{'file': q['file'], 'line': q['line'], 'text': q['error'][:300]}])
        unseen = [q for q in checked if q['status'] == 'not_observed']
        unresolved_parameters = [q for q in checked if q['status'] == 'unresolved_parameter_schema']
        if unresolved_parameters and not bad and 'F1C-GEN12' not in status:
            status['F1C-GEN12'] = {'status': 'not_assessed', 'reason':
                'структура табличного параметра неизвестна: проверка не установила наличие или отсутствие поля (%d запросов)' % len(unresolved_parameters)}
        if not bad and not unseen:
            temp = sum(q['status'] == 'unresolved_temp_table' for q in checked)
            clean('F1C-GEN12', 'платформа разобрала %d текстов запросов без ошибок; не проверено: %d собираемых из частей, %d со ссылкой на временную таблицу другого запроса'
                  % (len(checked) - temp - len(unresolved_parameters), len(skipped), temp))
    # М4.14, М4.15, М4.22, М4.24, М4.28, М7.9: the platform's reading of each parsed query (СхемаЗапроса) and the storage indexes.
    # One query place and one table (or outer-joined alias) is one defect; several items on it charge the smallest (A02).
    observed = observations.get(queries.CASE) or {}
    if observed.get('checked') and 'storage' in observed:
        found = queries.extract(src)[0]
        parsed, unparsed, seen = 0, 0, set()
        for item in observed['checked']:
            if not item.get('schema'):
                unparsed += item.get('error', '') == '' and item.get('index', -1) < len(found)
                continue
            parsed += 1
            where = found[item['index']]
            for sign in queryschema.signs(item['schema'], observed['storage']):
                key = (sign['penalty'], where['file'], where['line'], sign['detail'])
                if key in seen:
                    continue
                seen.add(key)
                find(sign['penalty'], 'query.%s:%d.%s' % (where['file'], where['line'], sign['target']), '%s:%d — %s' % (where['file'], where['line'], sign['detail']),
                     [{'file': where['file'], 'line': where['line'], 'text': sign['detail']}])
        limits = 'платформа разобрала структуру %d запросов (не разобрано %d); виртуальные таблицы регистров бухгалтерии и расчёта и временные таблицы по индексам не проверяются' % (parsed, unparsed)
        for penalty in ('F1C-GEN14', 'F1C-GEN15', 'F1C-GEN22', 'F1C-GEN24', 'F1C-GEN28', 'F1C-PR09'):
            clean(penalty, 'признаков нет: ' + limits)
    if 'F1C-GEN01' not in status and attestation == []:
        clean('F1C-GEN01', 'невыполненных требований нет')

    # Items proved by requirements: no violation when every linked requirement passed on the control data.
    linked = {}
    for rid, penalties in REQUIREMENT_PENALTIES.items():
        for penalty in penalties:
            linked.setdefault(penalty, []).append(rid)
    for penalty, rids in linked.items():
        if status.get(penalty, {}).get('status') == 'violation':
            continue
        verdicts = [verdict[r]['verdict'] for r in rids if r in verdict]
        if verdicts and all(v == 'pass' for v in verdicts):
            clean(penalty, 'на контрольных данных выполнены требования ' + ', '.join(rids))
        elif verdicts:
            status.setdefault(penalty, {'status': 'not_assessed', 'reason': 'связанные требования не оценены или упали на ошибке в коде: ' + ', '.join(rids)})

    # М4.5: posting takes data from registers. The «manual» case adds a register entry with no source document before a
    # sale; BU02 checks the sale's cost and balance count it. If BU02 fails while the cost without a manual entry is
    # right (BU13, BU14), posting ignores what is only in the register. Reports are not checked this way.
    got = {r: verdict[r]['verdict'] for r in ('BU02', 'BU13', 'BU14') if r in verdict}
    if got.get('BU02') == 'fail' and got.get('BU13') == 'pass' and got.get('BU14') == 'pass' and not root_cause('BU02'):
        find('F1C-GEN05', 'requirement.BU02', 'проведение не учитывает запись регистра, введённую ручной операцией: себестоимость без неё верна (BU13, BU14), с ней — нет (BU02)')
    elif got.get('BU02') == 'pass':
        clean('F1C-GEN05', 'проведение учитывает запись регистра, введённую ручной операцией (BU02); отчёты так не проверяются')
    else:
        status.setdefault('F1C-GEN05', {'status': 'not_assessed', 'reason': 'BU02 не выполнено по другой причине или не оценено'})

    # М4.5 (#std477): a register is self-sufficient; a query reading attributes of the registrar through a dot
    # («Т.Регистратор.Склад») takes data from documents, not from the register.
    texts = [(f.relative_to(src).as_posix(), t, line) for f in sorted(src.rglob('*.bsl')) if 'BenchmarkObserver' not in f.parts
             for t, line in lex(read(f))[1]]
    texts += [(f.relative_to(src).as_posix(), read(f), 1) for f in sorted(src.rglob('Templates/*/Ext/Template.xml'))]
    registrar = ['%s:%d %s' % (f, line + t.count('\n', 0, m.start()), m.group(0)) for f, t, line in texts
                 for m in re.finditer(r'(?<![\wЁё.])[\wЁё]+\.Регистратор\.(?!Ссылка(?![\wЁё]))[\wЁё]+', t)]
    if registrar:
        find('F1C-GEN05', 'code.registrar_fields', 'запрос берёт данные из документа-регистратора, а не из регистра: ' + '; '.join(registrar[:3]))
    # М4.10: documents in posting are ordered by their point in time; by Дата alone documents of one date come in no
    # defined order (FIFO/LIFO write-off by batches, settlements by invoices).
    by_date = ['%s:%d %s' % (f.relative_to(src).as_posix(), line + t.count('\n', 0, m.start()), x) for f in posting_modules(src) for t, line in lex(read(f))[1]
               for m in re.finditer(r'УПОРЯДОЧИТЬ\s+ПО(.*?)(?=;|\bИТОГИ\b|\bОБЪЕДИНИТЬ\b|\bДЛЯ\s+ИЗМЕНЕНИЯ\b|$)', t, re.S | re.I)
               for x in re.findall(r'[\wЁё]+\.[\wЁё]+\.Дата(?![\wЁё])', m.group(1))]
    if by_date:
        find('F1C-GEN10', 'code.order_by_date', 'документы упорядочены по Дата, а не по МоментВремени: порядок документов одной даты не определён: ' + '; '.join(by_date[:3]))

    # М4.12: posting with a zero divisor (an unfilled schedule, no days in the base) must not fail on division by zero.
    zero = observations.get('pr_zero') or {}
    divided = sorted(k for k, v in (zero.get('errors') or {}).items() if re.search(r'Деление на 0|Division by zero', str(v), re.I))
    if divided:
        find('F1C-GEN12', 'code.division_by_zero', 'проведение падает на делении на ноль при пустом графике или нулевой базе (сценарий pr_zero: %s)' % ', '.join(divided),
             [str(zero['errors'][k])[:300] for k in divided])

    # М7.13: the base of the records being calculated is read before they are written — it comes out empty.
    if list(src.glob('CalculationRegisters/*.xml')):
        early = base_before_write(src)
        if early:
            find('F1C-PR13', 'pr.base_before_write', 'база рассчитываемых записей читается до их записи — она будет пустой: '
                 + '; '.join('%s:%d %s' % x for x in early[:3]))
    # М4.23: the main table of a calculation register joined with its own ДанныеГрафика — the virtual table already
    # holds every record with the schedule fields, the join only multiplies rows.
    joined = ['%s:%d %s' % (f, line, reg) for f, t, line in texts for part in t.split(';')
              for reg in re.findall(r'РегистрРасчета\.(\w+)\.ДанныеГрафика', part)
              if re.search(r'РегистрРасчета\.' + reg + r'\s+КАК', part) and re.search(r'СОЕДИНЕНИЕ', part, re.I)]
    if joined:
        find('F1C-GEN23', 'query.schedule_joined_to_main', 'основная таблица регистра расчёта соединяется с его же «Данными графика»: ' + '; '.join(joined[:3]))

    # М5.4: totals obtained in a form are not used in posting. The stand posts every document from code without
    # opening its form, so posting that passes all operational accounting requirements does not depend on the form.
    ou = [verdict[i]['verdict'] for i, s in section_of.items() if s == 'OU' and i in verdict]
    if ou and all(v == 'pass' for v in ou):
        clean('F1C-OU04', 'документы проводятся кодом стенда без открытия формы, и все требования оперативного учёта выполнены')
    else:
        status.setdefault('F1C-OU04', {'status': 'not_assessed', 'reason': 'не все требования оперативного учёта выполнены: зависимость от формы не исключена'})

    # М7.16: storno of calculation register records by the platform: ПолучитьДополнение() proposes the storno records by
    # the displacement rules. Records marked Сторно = Истина with no call to it anywhere are storno computed by hand.
    code = {f.relative_to(src).as_posix(): lex(read(f))[0] for f in sorted(src.rglob('*.bsl')) if 'BenchmarkObserver' not in f.parts}
    manual = [(f, c.count('\n', 0, m.start()) + 1) for f, c in code.items() for m in re.finditer(r'\.Сторно\s*=\s*Истина\b', c)]
    if any('ПолучитьДополнение' in c for c in code.values()):
        clean('F1C-PR16', 'сторно-записи получаются штатным методом ПолучитьДополнение()')
    elif manual:
        find('F1C-PR16', 'pr.manual_storno', 'записи помечаются Сторно = Истина без ПолучитьДополнение(): ' + ', '.join('%s:%d' % m for m in manual[:3]),
             [{'file': f, 'line': n, 'text': 'Сторно = Истина'} for f, n in manual[:20]])
    else:
        status.setdefault('F1C-PR16', {'status': 'not_assessed', 'reason': 'сторно в решении нет; его отсутствие — пункт PR15'})

    # М4.19: duplicate lines. dup_split must post like a single line (BU13, BU14 checked that line); dup_over must be
    # refused like the single line of «oversell» (BU10). Either failing while its single-line twin passes is the defect.
    codes = binding.get('account_codes') or {}
    split, over = observations.get('dup_split'), observations.get('dup_over')
    single = {r: verdict[r]['verdict'] for r in ('BU10', 'BU13', 'BU14') if r in verdict}
    if split and over and codes.get('goods') and codes.get('customers') and codes.get('profit'):
        # Cost is Dt profit Ct goods and revenue Dt customers Ct profit only: moving amounts between warehouses on the
        # goods account (Dt goods Ct goods) is a solution's own bookkeeping, not cost.
        rows = new_rows(split)
        cost = sum(Decimal(str(r['amount'])) for r in rows if r['debit'] == codes['profit'] and r['credit'] == codes['goods'])
        revenue = sum(Decimal(str(r['amount'])) for r in rows if r['debit'] == codes['customers'] and r['credit'] == codes['profit'])
        refused = not over.get('posted') and over.get('before') == over.get('after') and over.get('all_before') == over.get('all_after')
        wrong = []
        if not refused and single.get('BU10') == 'pass':
            wrong.append('документ с двумя строками 2 и 1 при остатке 2 на складе проведён, одной строкой 3 — отклонён: остаток контролируется по строкам')
        if not (split.get('posted') and cost == 52 and revenue == 80) and single.get('BU13') == 'pass' and single.get('BU14') == 'pass':
            wrong.append('продажа строками 1 и 1 дала себестоимость %s и выручку %s вместо 52 и 80, одной строкой — верно' % (cost, revenue))
        if wrong:
            find('F1C-GEN19', 'runtime.duplicate_lines', '; '.join(wrong))
        elif refused and split.get('posted') and cost == 52 and revenue == 80:
            clean('F1C-GEN19', 'строки с одним товаром проводятся как одна строка, контроль остатка — по документу')
    status.setdefault('F1C-GEN19', {'status': 'not_assessed', 'reason': 'сценарии с повторяющимися строками не наблюдались или однострочные не выполнены'})

    # М4.17: unposting the sale of «average» brings every financial register back to the state before it.
    average = observations.get('average') or {}
    if average.get('undo_error'):
        find('F1C-GEN17', 'runtime.unpost', 'отмена проведения расходной накладной падает: ' + average['undo_error'][:200])
    elif 'undone_all' in average:
        if average['undone_all'] == average.get('all_before'):
            clean('F1C-GEN17', 'после отмены проведения расходной накладной регистры вернулись к состоянию до её проведения')
        else:
            changed = sorted(k for k in set(average['undone_all']) | set(average.get('all_before') or {}) if average['undone_all'].get(k) != (average.get('all_before') or {}).get(k))
            find('F1C-GEN17', 'runtime.unpost', 'после отмены проведения расходной накладной не вернулись регистры: ' + ', '.join(changed))
    status.setdefault('F1C-GEN17', {'status': 'not_assessed', 'reason': 'расходная накладная в сценарии не проведена или отмена не наблюдалась'})

    # М8 business processes and М7.10, М7.12 recalculations, by metadata: only where the ticket makes the rule applicable.
    applies = {item['id']: item['applicability'] for item in catalogue['items']}
    for penalty, (state, why) in {**business_processes(src), **recalculations(src)}.items():
        if penalty == 'F1C-PR10' and policy.get('recalculation', {}).get('current_task_mode') == 'prohibited':
            status[penalty] = {'status': 'not_assessed', 'reason': 'билет запрещает перерасчёты; требования их настройки неприменимы'}
            continue
        if applies.get(penalty, 'not_applicable') == 'not_applicable':
            continue
        if state == 'violation':
            find(penalty, 'meta.' + penalty.split('-', 1)[1].lower(), why)
        elif state == 'no_violation_found':
            clean(penalty, why)
        else:
            status.setdefault(penalty, {'status': 'not_assessed', 'reason': why})

    # М4.25: a query result unloaded to a value table only to be walked once (Выбрать() walks it without the table).
    unloads = unloaded_once(src)
    for f, n, var in unloads:
        find('F1C-GEN25', 'code.unload.%s:%d' % (f, n), 'результат запроса выгружается в таблицу значений %s только для одного перебора: %s:%d' % (var, f, n),
             [{'file': f, 'line': n, 'text': var + ' = ….Выполнить().Выгрузить()'}])
    if not unloads:
        clean('F1C-GEN25', 'выгрузок результата запроса только ради одного перебора нет')

    # М4.27: the solution works as a managed application (main run mode; no ordinary forms of its own objects).
    config_text = read(src / 'Configuration.xml')
    # Forms of starter objects (the starter's query console has ordinary forms) are not the solution's.
    starter_objects = set(((starter or {}).get('objects_uuid') or {}).keys())
    ordinary = [f.relative_to(src).as_posix() for f in src.glob('*/*/Forms/*.xml')
                if f.parent.parent.parent.name + '/' + f.parent.parent.name not in starter_objects and '<FormType>Ordinary</FormType>' in read(f)]
    if prop(config_text, 'DefaultRunMode') not in (None, 'ManagedApplication'):
        find('F1C-GEN27', 'ui.run_mode', 'основной режим запуска — ' + prop(config_text, 'DefaultRunMode'))
    elif ordinary:
        find('F1C-GEN27', 'ui.run_mode', 'обычные формы: ' + ', '.join(ordinary[:5]))
    else:
        clean('F1C-GEN27', 'основной режим — управляемое приложение, обычных форм нет')
    clean('F1C-GEN30', 'сдача — одна конфигурация для всех разделов')

    reports = {p.stem for p in (src / 'Reports').glob('*.xml')}
    if not reports:
        for role in sorted(set(REPORT_REQUIREMENTS.values())):
            find('F1C-GEN02', 'report.' + role, 'в конфигурации нет ни одного отчёта: не реализован отчёт ' + role)
    else:
        status.setdefault('F1C-GEN02', {'status': 'not_assessed', 'reason': 'отчёты в конфигурации есть; соответствие каждого объявленного отчёта — по требованиям'})

    demo = gates.get('demo_data') or {}
    if demo.get('status') in ('not_declared', 'failed', 'empty'):
        find('F1C-GEN32', 'demo_data', 'демо-данные: ' + demo['status'] + (' — ' + str(demo.get('reason'))[:200] if demo.get('reason') else ''))
    elif demo.get('status') == 'present':
        clean('F1C-GEN32', 'процедура демо-данных проводит документы')

    mechanism_failed = [i for i in MECHANISM_REQUIREMENTS if verdict.get(i, {}).get('verdict') == 'fail']
    for i in mechanism_failed:
        find('F1C-GEN04', 'requirement.' + i, 'не соблюдён механизм, предписанный билетом: ' + i)

    # Batch 2: concrete signs in exported metadata.
    config = read(src / 'Configuration.xml')
    lock = prop(config, 'DataLockControlMode')
    # The agent has to switch the starter to managed locks on its own (М2.3.2). In the managed mode of the configuration
    # the platform ignores the mode of single objects; only in the mixed mode every register with totals and document
    # the solution uses must be switched too. An unused starter object is not a violation.
    used = [ref for sec, role in BINDING_DOCUMENTS if (ref := declared(binding, sec, role))]
    used += [ref for ref in (declared(binding, 'ou', 'stock'), declared(binding, 'objects', 'ledger')) if ref]
    used += [r['register'] for r in ((binding.get('pr') or {}).get('results') or [])]
    automatic = sorted({ref for ref in used if prop(object_xml(src, ref), 'DataLockControlMode') == 'Automatic'}) if lock == 'AutomaticAndManaged' else []
    if lock == 'Automatic' or automatic:
        find('F1C-GEN29', 'locks.mode', 'автоматический режим блокировок: ' + ', '.join((['конфигурация'] if lock == 'Automatic' else []) + automatic))
    else:
        # In the managed mode a posting that reads balances must lock them first (#std460, #std661). Which reads a
        # given lock covers needs the call graph, so only a solution with no БлокировкаДанных at all is a sign.
        posting = {f.relative_to(src).as_posix(): lex(read(f)) for f in posting_modules(src)}
        reads = [f for f, (_, strings) in posting.items() if any(re.search(r'\.(Остатки|ОстаткиИОбороты)\s*\(', s) for s, _ in strings)]
        # «ДЛЯ ИЗМЕНЕНИЯ» is the automatic-lock clause; in the managed mode it means nothing (#std460).
        for_update = ['%s:%d' % (f, line + text.count('\n', 0, m.start())) for f, (_, strings) in posting.items() for text, line in strings
                      for m in re.finditer(r'(?<![\wЁё])ДЛЯ\s+ИЗМЕНЕНИЯ(?![\wЁё])', text, re.I)]
        unlocked, late = lock_signs(src)
        if for_update:
            find('F1C-GEN29', 'locks.for_update', 'в запросах проведения автоматическая блокировка «ДЛЯ ИЗМЕНЕНИЯ» при управляемом режиме: ' + ', '.join(for_update[:3]))
        elif unlocked:
            find('F1C-GEN29', 'locks.none' if not any('БлокировкаДанных' in code for code, _ in posting.values()) else 'locks.unlocked_reads', 'проведение читает остатки регистров до записи их движений, а управляемой блокировки этих регистров нет нигде: ' + ', '.join(unlocked))
        elif late:
            find('F1C-GEN29', 'locks.after_read', 'управляемая блокировка устанавливается после чтения остатков (#std460: блокировать до чтения): ' + '; '.join(late[:3]))
        # #std648 2.1: data read and then changed are locked exclusively; a shared lock of a register whose movements the
        # solution writes leaves room for deadlocks.
        written_regs = {r for f in sorted(src.glob('Documents/*.xml')) for r in re.findall(r'MDObjectRef">(?:AccumulationRegister|AccountingRegister)\.(\w+)<', read(f))}
        shared = []
        for f in sorted(src.rglob('*.bsl')):
            if 'BenchmarkObserver' in f.parts:
                continue
            code = read(f)
            for m in re.finditer(r'(\w+)\s*=\s*\w+\.Добавить\(\s*"(?:РегистрНакопления|РегистрБухгалтерии)\.(\w+)"\s*\)', code):
                tail = code[m.end():m.end() + 600].split('Заблокировать')[0]
                if m.group(2) in written_regs and re.search(re.escape(m.group(1)) + r'\.Режим\s*=\s*РежимБлокировкиДанных\.Разделяемый', tail):
                    shared.append('%s: %s' % (f.relative_to(src), m.group(2)))
        if shared:
            find('F1C-GEN29', 'locks.shared_on_written', 'разделяемая блокировка регистра, движения которого записываются (#std648: исключительная до чтения): ' + '; '.join(shared[:3]))
        else:
            clean('F1C-GEN29', 'управляемый режим у конфигурации и у задействованных регистров и документов; правильность каждой блокировки в коде не проверяется')

    # М4.29 (owner decision A20): БлокироватьДляИзменения of a register whose totals splitting is off does not work as
    # meant (as the course «СпецКурс 1С 8.3» explains it); every reference that uses it has splitting on.
    no_split = []
    for f in posting_modules(src):
        for name in sorted(set(re.findall(r'Движения\.(\w+)\.БлокироватьДляИзменения\s*=\s*Истина', lex(read(f))[0]))):
            reg = read(src / 'AccumulationRegisters' / (name + '.xml')) or read(src / 'AccountingRegisters' / (name + '.xml'))
            if prop(reg, 'EnableTotalsSplitting') == 'false':
                no_split.append('%s: %s' % (f.relative_to(src), name))
    if no_split:
        find('F1C-GEN29', 'locks.lock_for_change_no_splitting', 'БлокироватьДляИзменения у регистра с выключенным разделением итогов: ' + ', '.join(no_split[:3]))
    # М4.28 (owner decision A21): a posted document writes its movements in the «Записывать выбранные» mode; with
    # «Записывать модифицированные» the platform writes modified sets itself and the posting method is not shown.
    modified = [p.stem for p in sorted(src.glob('Documents/*.xml'))
                if prop(read(p), 'Posting') == 'Allow' and prop(read(p), 'RegisterRecordsWritingOnPost') == 'WriteModified'
                and re.search(r'<RegisterRecords>\s*<xr:Item', read(p))]
    if modified:
        find('F1C-GEN28', 'posting.write_modified', 'проводимые документы в режиме «Записывать модифицированные»: ' + ', '.join(modified))
    # М4.1 (owner decision A19): the starter is the customer's system; removing its objects simplifies the task.
    # Only a submission built on the issued starter (same configuration identity) can have removed its objects.
    identity, present = configuration_identity(src) if (src / 'Configuration.xml').is_file() else (None, {})
    if starter and starter.get('objects_uuid') and identity and identity == starter.get('configuration_uuid'):
        removed = sorted(k for k in starter['objects_uuid'] if k not in present)
        if removed:
            find('F1C-GEN01', 'starter.objects_removed', 'из каркаса удалены объекты: ' + ', '.join(removed))

    stock = declared(binding, 'ou', 'stock')
    if stock:
        kind = prop(object_xml(src, stock), 'RegisterType')
        if kind == 'Turnovers':
            find('F1C-OU03', 'ou.stock_kind', stock + ': оборотный регистр, а для остатков деталей нужен регистр остатков')
        else:
            clean('F1C-OU03', stock + ': регистр остатков')
        clean('F1C-OU02', 'остатки ведутся в регистре накопления ' + stock)
    ledger = declared(binding, 'objects', 'ledger')
    if ledger:
        clean('F1C-BU02', 'бухгалтерский учёт в регистре бухгалтерии ' + ledger)
    results = [r['register'] for r in ((binding.get('pr') or {}).get('results') or [])]
    if results:
        clean('F1C-PR02', 'начисления в регистрах расчёта: ' + ', '.join(results))
        clean('F1C-PR17', 'объявлены регистры расчёта, не накопления')
        linked, extra = [], []
        for ref in results:
            text = object_xml(src, ref)
            if prop(text, 'ActionPeriod') == 'true' and (prop(text, 'Schedule') or '').strip():
                linked.append(ref)
            chart = (prop(text, 'ChartOfCalculationTypes') or '')
            if prop(text, 'ActionPeriod') == 'true' and chart and prop(object_xml(src, chart), 'ActionPeriodUse') == 'false':
                extra.append(ref)
        # A schedule link on a dimension is right when the schedule depends on that dimension (М7.5 «или наоборот»):
        # not judged. Only a missing link is a sign, and only where the ticket asks for work by schedules (Т4.3).
        if 'PR03' not in section_of:
            status['F1C-PR05'] = {'status': 'not_assessed', 'reason': 'билет не требует работы по графику'}
        elif not linked:
            find('F1C-PR05', 'pr.schedule_link', 'ни у одного регистра расчёта нет периода действия со связью с графиком')
        else:
            clean('F1C-PR05', 'связь с графиком: ' + ', '.join(linked))
        if extra:
            find('F1C-PR04', 'pr.action_period', 'период действия у регистра, чьи виды расчёта его не используют: ' + ', '.join(extra))
        else:
            clean('F1C-PR04', 'период действия согласован с видами расчёта')
        # М7.14 (owner decision A15, as the examiner П. С. Белоусов explains it): after the results are calculated, the
        # set of a register with an action period is written again with ТолькоЗапись (or without the actual period
        # table); a plain Записать() rebuilds the actual action period table for nothing.
        idle = rewrites(src)
        if idle:
            find('F1C-PR14', 'pr.actual_period', 'после расчёта набор с периодом действия перезаписывается целиком, с пересчётом фактического периода действия '
                 '(нужно Записать(, Истина)): ' + '; '.join('%s:%d %s' % (f, line, statement) for f, line, _, statement in idle))
        else:
            clean('F1C-PR14', 'после расчёта наборы с периодом действия записываются без перезаписи фактического периода действия')

    # М6.6: the quantity resource of the ledger is kept only where the account has the quantity flag, it is not a
    # balance resource, and the goods account of the binding has that flag on (as every reference solution does).
    if ledger:
        ledger_text = object_xml(src, ledger)
        resources = {prop(body, 'Name'): body for body in re.findall(r'<Resource uuid="[^"]*">(.*?)</Resource>', ledger_text, re.S)}
        quantity = [n for n in resources if re.search(r'кол|qty|quant', n or '', re.I)]
        wrong = []
        for name in quantity:
            body = resources[name]
            if not (prop(body, 'AccountingFlag') or '').strip():
                wrong.append('ресурс %s без признака учёта — количество ведётся на всех счетах' % name)
            if prop(body, 'Balance') == 'true':
                wrong.append('ресурс %s балансовый' % name)
        chart_ref = prop(ledger_text, 'ChartOfAccounts') or ''
        goods = (binding.get('account_codes') or {}).get('goods')
        flags = re.findall(r'<AccountingFlag uuid="[^"]*">\s*<Properties>\s*<Name>(\w+)</Name>', object_xml(src, chart_ref)) if chart_ref else []
        quantity_flags = [f for f in flags if re.search(r'кол|qty|quant', f, re.I)]
        if goods and quantity_flags and chart_ref:
            predefined = read(src / 'ChartsOfAccounts' / chart_ref.split('.', 1)[1] / 'Ext' / 'Predefined.xml')
            item = next((i for i in re.findall(r'<Item\b.*?</Item>', predefined, re.S) if prop(i, 'Code') == goods), None)
            if item is not None and not re.search(r'AccountingFlag\.(%s)">true<' % '|'.join(quantity_flags), item):
                wrong.append('у счёта товаров %s не включён признак учёта %s' % (goods, quantity_flags[0]))
        wrong += ['небалансовый ресурс %s без признака учёта — ведётся на всех счетах' % n for n, body in resources.items()
                  if n not in quantity and prop(body, 'Balance') == 'false' and not (prop(body, 'AccountingFlag') or '').strip()]
        linked = {(prop(body, 'AccountingFlag') or '').rsplit('.', 1)[-1] for body in resources.values()}
        wrong += ['признак учёта %s плана счетов не указан ни у одного ресурса регистра — не действует' % f for f in flags if f not in linked]
        if wrong:
            find('F1C-BU06', 'bu.flags', '; '.join(wrong))
        elif quantity:
            clean('F1C-BU06', 'количество небалансовое, с признаком учёта; счёт товаров количественный')
        else:
            status['F1C-BU06'] = {'status': 'not_assessed', 'reason': 'в регистре бухгалтерии нет количественного ресурса'}

    # М6.7, М6.8: subconto of the binding's accounts. Each account item of the chart is read up to the next item start
    # (child accounts follow their parent's own subconto list).
    accounts_ref = (binding.get('objects') or {}).get('accounts')
    codes = binding.get('account_codes') or {}
    if ledger and accounts_ref:
        chart_name = accounts_ref.split('.', 1)[1]
        chart_xml = read(src / 'ChartsOfAccounts' / (chart_name + '.xml'))
        accounts = {prop(chunk, 'Code'): chunk.split('<ChildItems>')[0] for chunk in read(src / 'ChartsOfAccounts' / chart_name / 'Ext' / 'Predefined.xml').split('<Item id=')[1:]}
        kinds_ref = prop(chart_xml, 'ExtDimensionTypes') or ''
        kinds = {}
        if kinds_ref.count('.') == 1:
            for chunk in read(src / 'ChartsOfCharacteristicTypes' / kinds_ref.split('.', 1)[1] / 'Ext' / 'Predefined.xml').split('<Item id=')[1:]:
                kinds[prop(chunk, 'Name')] = {t.split(':', 1)[-1] for t in re.findall(r'<v8:Type[^>]*>([^<]+)</v8:Type>', chunk)}

        def subconto(code):
            """[(kind name, catalog types, turnover only, {accounting flag: on})] of an account."""
            body = accounts.get(code) or ''
            return [(name, kinds.get(name, set()), turnover == 'true', {f: v == 'true' for f, v in re.findall(r'ExtDimensionAccountingFlag\.(\w+)">(\w+)<', flags)})
                    for name, turnover, flags in re.findall(r'<ExtDimensionType name="[^"]*\.(\w+)">\s*<Turnover>(\w+)</Turnover>(.*?)</ExtDimensionType>', body, re.S)]

        # М6.7: cost is the company mean per item (Т3.13), so the goods account keeps no amount per warehouse.
        ledger_text = object_xml(src, ledger)
        amount = ((binding.get('fields') or {}).get('ledger') or {}).get('amount') or 'Сумма'
        amount_body = next((b for b in re.findall(r'<Resource uuid="[^"]*">(.*?)</Resource>', ledger_text, re.S) if prop(b, 'Name') == amount), '')
        sum_flag = (prop(amount_body, 'ExtDimensionAccountingFlag') or '').rsplit('.', 1)[-1]
        warehouses = 'CatalogRef.' + ((binding.get('objects') or {}).get('warehouses') or '.').split('.', 1)[1]
        on_goods = [k for k in subconto(codes.get('goods')) if warehouses in k[1]]
        ext_flags = re.findall(r'<ExtDimensionAccountingFlag uuid="[^"]*">\s*<Properties>\s*<Name>(\w+)</Name>', chart_xml)
        ext_linked = {(prop(b, 'ExtDimensionAccountingFlag') or '').rsplit('.', 1)[-1] for b in re.findall(r'<Resource uuid="[^"]*">(.*?)</Resource>', ledger_text, re.S)}
        idle_ext = [f for f in ext_flags if f not in ext_linked]
        if idle_ext:
            find('F1C-BU07', 'bu.subconto_flags', 'признак учёта субконто %s заведён в плане счетов, но не указан ни у одного ресурса регистра — не действует' % ', '.join(idle_ext))
        elif not on_goods:
            status.setdefault('F1C-BU07', {'status': 'not_assessed', 'reason': 'у счёта товаров нет субконто складов'})
        elif not sum_flag:
            # Owner decision A16: subconto accounting flags not set up at all is «не реализована настройка» (М6.7).
            find('F1C-BU07', 'bu.subconto_flags', 'признаки учёта субконто не заведены: сумма ведётся по всем субконто, в том числе по складам, а себестоимость — средняя по номенклатуре всей компании (Т3.13)')
        elif any(k[3].get(sum_flag) for k in on_goods):
            find('F1C-BU07', 'bu.subconto_flags', 'у субконто %s счёта товаров включён признак %s: сумма ведётся по складам, а себестоимость — средняя по номенклатуре всей компании (Т3.13)' % (on_goods[0][0], sum_flag))
        else:
            clean('F1C-BU07', 'по субконто складов счёта товаров ведётся только количество (признак %s выключен)' % sum_flag)
        # М6.8: the profit account serves the sales report by turnovers (Т3.16, Т3.17), no balances by its analytics.
        on_profit = subconto(codes.get('profit'))
        kept = [k[0] for k in on_profit if not k[2]]
        if kept:
            find('F1C-BU08', 'bu.profit_balances', 'у счёта прибылей и убытков хранятся остатки по субконто ' + ', '.join(kept) + ': отчёту о продажах нужны только обороты')
        elif on_profit:
            clean('F1C-BU08', 'субконто счёта прибылей и убытков только оборотные')
        else:
            status.setdefault('F1C-BU08', {'status': 'not_assessed', 'reason': 'у счёта прибылей и убытков нет субконто'})

    # М6.5: analytics that depends on the account (items, warehouses) kept as ledger dimensions exists on every account;
    # it belongs to the subconto of the accounts that need it (owner decision 12.10.2026).
    if ledger:
        objects = binding.get('objects') or {}
        analytic = {objects[k].split('.', 1)[1]: k for k in ('items', 'warehouses') if objects.get(k)}
        dims = re.findall(r'<Dimension uuid="[^"]*">(.*?)</Dimension>', object_xml(src, ledger), re.S)
        extra = ['%s (%s)' % (prop(d, 'Name'), catalog) for d in dims
                 for catalog in re.findall(r'<v8:Type>cfg:CatalogRef\.(\w+)</v8:Type>', d) if catalog in analytic]
        if extra:
            find('F1C-BU05', 'bu.dimensions', 'аналитика счетов вынесена в измерения регистра бухгалтерии и есть у всех счетов: ' + ', '.join(extra))
        else:
            clean('F1C-BU05', 'номенклатура и склады не заведены измерениями регистра бухгалтерии')

    accounts = (starter or {}).get('predefined_accounts')
    if accounts:
        chart = read(src / 'ChartsOfAccounts' / (accounts['chart'].split('.', 1)[1]) / 'Ext' / 'Predefined.xml')
        have = set(re.findall(r'<Name>([^<]+)</Name>', chart))
        missing = [a['name'] for a in accounts['accounts'] if a['name'] not in have]
        if missing:
            find('F1C-BU11', 'bu.accounts_removed', 'из плана счетов каркаса удалены счета: ' + ', '.join(missing))
        else:
            clean('F1C-BU11', 'все %d счетов каркаса на месте' % len(accounts['accounts']))

    ou_objects = (binding.get('ou') or {}).get('objects') or {}
    duplicated = [role for role in ('receipt', 'sale') if ou_objects.get(role) and declared(binding, 'objects', role) and ou_objects[role] != declared(binding, 'objects', role)]
    if duplicated:
        find('F1C-GEN31', 'shared.invoices', 'накладные разделов — разные виды документов: ' + ', '.join(
            '%s и %s' % (declared(binding, 'objects', r), ou_objects[r]) for r in duplicated))
    elif ou_objects:
        clean('F1C-GEN31', 'приходная и расходная накладные общие для разделов')

    starter_documents = set(((starter or {}).get('objects') or {}).get('Документы') or [])
    needed = {ref.split('.', 1)[1] for sec, role in BINDING_DOCUMENTS if (ref := declared(binding, sec, role))}
    def named_in_ticket(path):
        text = read(path)
        synonym = re.search(r'<Synonym>.*?<v8:content>([^<]*)</v8:content>', text, re.S)
        names = {path.stem.lower(), (synonym.group(1) if synonym else '').strip().lower()}
        return any(t.lower() in names or t.replace(' ', '').lower() in names for t in TICKET_DOCUMENTS)
    own = sorted(p.stem for p in (src / 'Documents').glob('*.xml') if p.stem not in starter_documents | needed and not named_in_ticket(p))
    for name in own:
        find('F1C-GEN33', 'document.' + name, 'собственный вид документа, не описанный в задании: ' + name)
    if not own:
        clean('F1C-GEN33', 'других видов документов нет')

    # Batch 3: concrete signs in the posting code (documents and common modules, not the demo-data module).
    signs = scan(src, binding)
    def where(items):
        return [{'file': f, 'line': n, 'text': t} for f, n, t in items[:20]]
    def first(items):
        return '; '.join('%s:%d' % (f, n) for f, n, _ in items[:3]) + (' и ещё %d' % (len(items) - 3) if len(items) > 3 else '')
    if signs['loop_reads']:
        find('F1C-GEN20', 'code.loop_reads', 'данные базы читаются в цикле по записям: ' + first(signs['loop_reads']), where(signs['loop_reads']))
    elif signs['unknown_loop_reads']:
        status['F1C-GEN20'] = {'status': 'not_assessed', 'reason': 'тип промежуточного значения не установлен: ' + first(signs['unknown_loop_reads'])}
    else:
        clean('F1C-GEN20', 'запросов и чтений регистров в циклах по данным не найдено')
    virtual = signs['empty_virtual_parameters'] + signs['where_on_dimension']
    if virtual:
        find('F1C-GEN21', 'code.virtual_parameters', 'параметры виртуальной таблицы не заданы или заменены условием ГДЕ: '
             + '; '.join('%s:%d %s' % (f, n, t) for f, n, t in virtual[:3]), where(virtual))
    else:
        clean('F1C-GEN21', 'у виртуальных таблиц заданы параметры, отборы по измерениям не вынесены в ГДЕ')
    if binding.get('pr'):
        if signs['schedule_table']:
            find('F1C-PR06', 'pr.schedule_table', 'данные графика читаются из таблицы регистра сведений: ' + first(signs['schedule_table']), where(signs['schedule_table']))
        else:
            clean('F1C-PR06', 'в коде проведения нет запросов к таблице регистра графиков')
        if signs['calculation_main_table']:
            find('F1C-PR08', 'pr.base_main_table', 'база берётся из основной таблицы регистра расчёта, БазаНачисления нигде не используется: '
                 + first(signs['calculation_main_table']), where(signs['calculation_main_table']))
        else:
            clean('F1C-PR08', 'база получается механизмом регистра расчёта или основная таблица не читается')
    if 'PR14' not in section_of:
        status['F1C-PR11'] = {'status': 'not_assessed', 'reason': 'билет не запрещает перерасчёты'}
    elif verdict.get('PR14', {}).get('verdict') == 'fail':
        # The same defect as a failed Т4.14 (no recalculations): one penalty, the smallest applicable.
        find('F1C-PR11', 'requirement.PR14', 'подтверждено нарушение запрета использования перерасчётов (Т4.14)')
    elif signs['recalculations'] or verdict.get('PR14', {}).get('verdict') == 'inconclusive':
        status['F1C-PR11'] = {'status': 'not_assessed', 'reason': 'наличие объекта не доказывает использование перерасчётов; runtime-доказательство пока не получено (A08)'}
    else:
        clean('F1C-PR11', 'перерасчётов нет')

    # Practices of the examiner and of the course (owner decision A24): each violation is charged under its ATT83PL item.
    practices = {k: {'status': st, 'reason': why} for k, (st, why) in {**examiner_signs(src), **course_signs(src), **standard_signs(src)}.items()} if src and Path(src).is_dir() else {}
    for practice, penalty in PRACTICE_PENALTIES.items():
        if (practices.get(practice) or {}).get('status') == 'violation':
            find(penalty, 'practice.' + practice, practices[practice]['reason'])

    for item in catalogue['items']:
        if item['applicability'] in ('applicable', 'conditional'):
            status.setdefault(item['id'], {'status': 'not_assessed', 'reason': 'детектор ещё не реализован'})
    score = score_bound(findings, catalogue, policy)
    gates_out = {'core': 'not_passed' if any(a == 'not_passed' for a, _ in attestation) else 'not_attested' if attestation else 'passed',
                 'core_sections': {s: a for a, s in attestation},
                 'locks': 'violated' if status.get('F1C-GEN29', {}).get('status') == 'violation' else 'passed',
                 'mechanisms': 'violated' if mechanism_failed else 'no_violation_found'}
    if gates_out['core'] == 'not_passed':
        score = dict(score, attestation='not_passed_required_section_absent', grade='unsatisfactory')
    elif gates_out['core'] == 'not_attested' and score['attestation'] == 'undetermined':
        score = dict(score, attestation='not_attested_required_section_unverifiable')
    return {'schema_version': 1, 'policy': policy['policy_id'], 'findings': findings, 'statuses': status, 'gates': gates_out, 'score': score,
            'assessed': sorted(k for k, v in status.items() if v['status'] != 'not_assessed'), 'examiner': practices}
