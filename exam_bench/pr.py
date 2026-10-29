"""Periodic calculations (ticket section Б4): binding check, scenarios, observer code, reference model and verdicts.

The solver declares its payroll objects in binding["pr"]. The stand fills departments, work schedules, rates,
the bonus scale and employees, posts accrual documents and reads the declared calculation registers grouped by
employee, department, calculation type and month of the action period (registration period when the register
has no action period). Expected amounts come from a small reference model of the ticket rules (Q06-Q08).
"""
import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .ou import IDENT, literal, manager, q, register_write, document_code, split

OBJECTS = {'employees': 'Catalog', 'departments': 'Catalog', 'schedules': 'InformationRegister', 'rates': 'InformationRegister',
           'scale': 'InformationRegister', 'accrual': 'Document'}
FIELDS = {'schedules': ('department', 'date', 'hours', 'days'), 'rates': ('employee', 'department', 'rate'),
          'scale': ('threshold', 'percent'), 'employees': ('seniority_start', 'initial_seniority'),
          'accrual': ('employee', 'department', 'calc_type', 'start', 'end', 'registration')}
REQUIRED = {'schedules': ('department', 'date', 'hours'), 'rates': ('employee', 'rate'), 'scale': ('threshold', 'percent'),
            'employees': ('seniority_start',), 'accrual': ('employee', 'department', 'calc_type', 'start', 'end')}
UNITS = ('years', 'months', 'days')
ROLES = ('tariff', 'bonus', 'trip')


def check(src, pr):
    """Declared payroll objects exist and fields are identifier paths; returns True or raises ValueError."""
    from .submission import descriptor
    if not isinstance(pr, dict):
        raise ValueError('binding.pr must be an object')
    objects = pr.get('objects', {})
    for role, kind in OBJECTS.items():
        ref = objects.get(role)
        if not isinstance(ref, str) or not ref.startswith(kind + '.'):
            raise ValueError('pr.objects.%s must be %s.<name>' % (role, kind))
        descriptor(Path(src), ref)
    results = pr.get('results')
    if not isinstance(results, list) or not results:
        raise ValueError('pr.results lists the calculation registers with employee, department and result fields')
    for r in results:
        if not isinstance(r, dict) or not str(r.get('register', '')).startswith('CalculationRegister.'):
            raise ValueError('pr.results[].register must be CalculationRegister.<name>')
        descriptor(Path(src), r['register'])
        if any(not IDENT.fullmatch(str(r.get(k, ''))) for k in ('employee', 'department', 'result')):
            raise ValueError('pr.results[] needs employee, department and result fields')
    types = pr.get('calc_types', {})
    if set(types) != set(ROLES) or not all(isinstance(v, str) and re.fullmatch(r'ChartOfCalculationTypes\.\w+\.\w+', v) for v in types.values()):
        raise ValueError('pr.calc_types maps tariff, bonus and trip to ChartOfCalculationTypes.<chart>.<predefined>')
    fields = pr.get('fields', {})
    for role, need in REQUIRED.items():
        f = fields.get(role, {})
        if set(need) - set(f) or set(f) - set(FIELDS[role]):
            raise ValueError('pr.fields.%s needs %s' % (role, ', '.join(need)))
        for path in f.values():
            if not all(IDENT.fullmatch(p) for p in str(path).split('.')) or str(path).count('.') > 1:
                raise ValueError('pr.fields paths are <attribute> or <table>.<attribute>: ' + str(path))
    if pr.get('scale_unit') not in UNITS[:2]:
        raise ValueError('pr.scale_unit is years or months')
    if 'initial_seniority' in fields['employees'] and pr.get('initial_unit') not in UNITS:
        raise ValueError('pr.initial_unit is years, months or days')
    return True


D = dt.date
WEEK = {'A': {0: 8, 1: 8, 2: 8, 3: 8, 4: 8}, 'B': {0: 6, 1: 6, 2: 6, 3: 6}, 'C': {0: 7, 1: 7, 2: 7, 3: 7, 4: 7}}
SCHEDULE_FROM, SCHEDULE_TO = D(2024, 9, 1), D(2025, 4, 30)
ACCOUNTING_START = D(2025, 1, 1)
SCALE = [(0, 4), (1, 9), (3, 16)]  # lower bound in years, percent; deliberately not the 5/10/15 of the ticket example


def month(d):
    return D(d.year, d.month, 1)


def month_end(d):
    return D(d.year + d.month // 12, d.month % 12 + 1, 1) - dt.timedelta(1)


def add_months(d, n):
    m = d.year * 12 + d.month - 1 + n
    return D(m // 12, m % 12 + 1, 1)


def full(m):
    """A whole calendar month as (start, end)."""
    return (month(m), month_end(m))


def row(kind, emp, dept, start, end):
    return (kind, emp, dept, start, end)


def tariff_months(emp, dept, months):
    return [row('tariff', emp, dept, *full(m)) for m in months]


# Scenarios. Employees: name -> seniority start. Rates: (employee, from, rate), the same for every department.
# Steps: ('doc', label, date, rows, expected_posted) and ('report', label, month).
CASES = {
    # Part-time in A and B, rate change mid-January (January keeps the rate at the start of the period), new rate in
    # February; one document with January and February rows; a tariff row crossing months must be refused.
    'pr_tariff': {'departments': 'AB', 'employees': {'E1': D(2020, 1, 1)},
                  'rates': [('E1', D(2024, 12, 1), 100), ('E1', D(2025, 1, 15), 200), ('E1', D(2025, 2, 1), 300)],
                  'steps': [('doc', 'mixed', D(2025, 2, 28), [row('tariff', 'E1', 'A', *full(D(2025, 1, 1))), row('tariff', 'E1', 'B', *full(D(2025, 1, 1))),
                                                                row('tariff', 'E1', 'A', *full(D(2025, 2, 1)))], True),
                            ('doc', 'span', D(2025, 3, 10), [row('tariff', 'E1', 'A', D(2025, 3, 10), D(2025, 4, 3))], False),
                            ('doc', 'part', D(2025, 3, 31), [row('tariff', 'E1', 'A', D(2025, 3, 10), D(2025, 3, 31))], True)]},
    # Trip from B (Mon-Thu, 6 h) 27.01-04.02 entered before the January and February tariffs; daily rate from October-December.
    'pr_trip': {'departments': 'AB', 'employees': {'E4': D(2020, 1, 1)},
                'rates': [('E4', D(2024, 1, 1), 10), ('E4', D(2024, 12, 1), 15), ('E4', D(2025, 1, 1), 20)],
                'steps': [('doc', 'oct', D(2024, 10, 31), tariff_months('E4', 'B', [D(2024, 10, 1)]), True),
                          ('doc', 'nov', D(2024, 11, 30), tariff_months('E4', 'B', [D(2024, 11, 1)]), True),
                          ('doc', 'dec', D(2024, 12, 31), tariff_months('E4', 'B', [D(2024, 12, 1)]), True),
                          ('doc', 'trip', D(2025, 1, 27), [row('trip', 'E4', 'B', D(2025, 1, 27), D(2025, 2, 4))], True),
                          ('doc', 'jan', D(2025, 1, 31), tariff_months('E4', 'B', [D(2025, 1, 1)]), True),
                          ('doc', 'feb', D(2025, 2, 28), tariff_months('E4', 'B', [D(2025, 2, 1)]), True)]},
    # Bonuses for February: heads H (A, 2 years before accounting), G (B, 5 years, on a trip 10-14.02), K (C, hired 01.01.2025).
    # Bases are January tariffs of their departments without the head; W2 works in A and B. March bonus of H checks the report month.
    'pr_bonus': {'departments': 'ABC', 'employees': {'H': D(2023, 1, 1), 'G': D(2020, 1, 1), 'K': D(2025, 1, 1), 'W1': D(2024, 1, 1),
                                                     'W2': D(2024, 1, 1), 'W3': D(2024, 1, 1), 'W4': D(2024, 1, 1)},
                 'rates': [(e, D(2024, 1, 1), r) for e, r in (('H', 50), ('G', 40), ('K', 35), ('W1', 10), ('W2', 20), ('W3', 30), ('W4', 25))],
                 'steps': [('doc', 'g_prev', D(2024, 12, 31), tariff_months('G', 'B', [D(2024, 11, 1), D(2024, 12, 1)]), True),
                           ('doc', 'jan', D(2025, 1, 31), [r for e, d in (('H', 'A'), ('W1', 'A'), ('W2', 'A'), ('W2', 'B'), ('G', 'B'), ('W3', 'B'), ('K', 'C'), ('W4', 'C'))
                                                           for r in tariff_months(e, d, [D(2025, 1, 1)])], True),
                           ('doc', 'trip', D(2025, 2, 10), [row('trip', 'G', 'B', D(2025, 2, 10), D(2025, 2, 14))], True),
                           # One document with a tariff row and bonus rows: several calculation types in one document (Б4.10.2).
                           ('doc', 'feb', D(2025, 2, 28), tariff_months('W1', 'A', [D(2025, 2, 1)]) + [row('bonus', h, d, *full(D(2025, 2, 1))) for h, d in (('H', 'A'), ('G', 'B'), ('K', 'C'))], True),
                           ('doc', 'mar', D(2025, 3, 31), [row('bonus', 'H', 'A', *full(D(2025, 3, 1)))], True),
                           ('report', 'report_feb', D(2025, 2, 1))]},
}
# The same data as pr_trip with the trip entered after the tariffs it displaces (Б4.8).
CASES['pr_backdate'] = dict(CASES['pr_trip'], steps=[s for s in CASES['pr_trip']['steps'] if s[1] != 'trip'] + [s for s in CASES['pr_trip']['steps'] if s[1] == 'trip'])
# Zero divisors (М4.12): a tariff in a department whose schedule is not filled (norm 0) and a trip of an employee with
# no accruals in the base period (0 days in the base). Posting may accept or refuse, but not fail on division by zero.
CASES['pr_zero'] = {'departments': 'AZ', 'unscheduled': 'Z', 'employees': {'N1': D(2025, 1, 1)},
                    'rates': [('N1', D(2024, 12, 1), 100)],
                    'steps': [('doc', 'no_schedule', D(2025, 1, 31), tariff_months('N1', 'Z', [D(2025, 1, 1)]), True),
                              ('doc', 'no_base', D(2025, 1, 13), [row('trip', 'N1', 'A', D(2025, 1, 13), D(2025, 1, 17))], True)]}

RULES = {'PR01': 'monthly accrual by the deviation method: a trip reduces the month tariff', 'PR02': 'part-time: one employee in two departments',
         'PR03': 'hours by the schedule of each department', 'PR04': 'tariff = rate x hours actually worked',
         'PR05': 'rate history kept in a periodic register with daily periodicity', 'PR06': 'rate at the start of the calculation period',
         'PR07': 'head bonus: percent of the previous month tariffs of the department without the head',
         'PR08': 'percent from the scale entered by the user', 'PR09': 'seniority counted before the start of accounting',
         'PR10': 'no tariff and no bonus during a trip', 'PR11': 'trip days by the schedule of the sending department',
         'PR12': 'daily rate: accruals / worked days of the three previous months', 'PR13': 'trip entered back-dated',
         'PR14': 'no recalculation objects found (Q09: signs only)', 'PR15': 'accruals entered by the accrual document, one or several kinds per document',
         'PR16': 'tariff row crossing a month is refused', 'PR17': 'trip may cross months', 'PR18': 'one document with rows of different periods',
         'PR19': 'bonus report for one calendar month'}


def hours(dept, d):
    return WEEK[dept].get(d.weekday(), 0) if SCHEDULE_FROM <= d <= SCHEDULE_TO else 0


def days(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(1)


def model(case, trip_day=None, previous=(3, 2, 1)):
    """Expected results {(employee, department, role, month): Decimal} of the documents expected to post.

    trip_day and previous describe how trip days are counted and which months give the daily rate; the defaults are the
    statement's rule (days of the department schedule, the three previous months), others model typical errors."""
    trip_day = trip_day or (lambda dept, d: bool(hours(dept, d)))
    rows = [r for s in case['steps'] if s[0] == 'doc' and s[4] for r in s[3]]
    trips = [r for r in rows if r[0] == 'trip']
    rates = sorted(case['rates'], key=lambda r: r[1])

    def rate(emp, on):
        found = [r for e, since, r in rates if e == emp and since <= on]
        return Decimal(found[-1]) if found else Decimal(0)

    def on_trip(emp, d):
        return any(e == emp and s <= d <= f for _, e, _, s, f in trips)

    out = {}

    def add(key, value):
        out[key] = out.get(key, Decimal(0)) + value
    for _, emp, dept, s, f in (r for r in rows if r[0] == 'tariff'):
        add((emp, dept, 'tariff', month(s)), rate(emp, month(s)) * sum(hours(dept, d) for d in days(s, f) if not on_trip(emp, d)))
    for _, emp, dept, s, f in trips:
        prev = [add_months(month(s), -n) for n in previous]
        accrued = sum((v for (e, dd, _, m), v in out.items() if e == emp and dd == dept and m in prev), Decimal(0))
        worked = sum(1 for _, e, dd, ts, tf in rows if _ == 'tariff' and e == emp and dd == dept and month(ts) in prev
                     for d in days(ts, tf) if trip_day(dept, d) and not on_trip(emp, d))
        daily = accrued / worked if worked else Decimal(0)
        for d in days(s, f):
            if trip_day(dept, d):
                add((emp, dept, 'trip', month(d)), daily)
    for _, head, dept, s, f in (r for r in rows if r[0] == 'bonus'):
        base = sum((v for (e, dd, role, m), v in out.items() if role == 'tariff' and dd == dept and e != head and m == add_months(month(s), -1)), Decimal(0))
        start = case['employees'][head]
        end = month_end(s)
        years = Decimal((end - start).days) / Decimal('365.25')
        pct = [p for bound, p in SCALE if years >= bound][-1]
        planned = [d for d in days(s, f) if hours(dept, d)]
        factor = Decimal(sum(1 for d in planned if not on_trip(head, d))) / Decimal(len(planned))
        add((head, dept, 'bonus', month(s)), base * pct / 100 * factor)
    return out


def trip_by_month(case, trip_day=None, previous=(3, 2, 1)):
    """Second reading of Б4.7.4 (owner: both accepted): each month's part of a trip has its own daily rate from the
    three months before that month, with all their accruals, earlier parts of the same trip included."""
    rows = [r for s in case['steps'] if s[0] == 'doc' and s[4] for r in s[3]]
    trips = [r for r in rows if r[0] == 'trip']
    trip_day = trip_day or (lambda dept, d: bool(hours(dept, d)))
    base = {k: v for k, v in model(case, trip_day, previous).items() if k[2] != 'trip'}

    def on_trip(emp, d):
        return any(e == emp and s <= d <= f for _, e, _, s, f in trips)
    out = {}
    for _, emp, dept, s, f in trips:
        months = sorted({month(d) for d in days(s, f) if trip_day(dept, d)})
        for m in months:
            prev = [add_months(m, -n) for n in previous]
            accrued = sum((v for (e, dd, _, mm), v in list(base.items()) + list(out.items()) if e == emp and dd == dept and mm in prev), Decimal(0))
            worked = sum(1 for kind, e, dd, ts, tf in rows if kind == 'tariff' and e == emp and dd == dept and month(ts) in prev
                         for d in days(ts, tf) if trip_day(dept, d) and not on_trip(emp, d))
            daily = accrued / worked if worked else Decimal(0)
            count = sum(1 for d in days(s, f) if trip_day(dept, d) and month(d) == m)
            out[(emp, dept, 'trip', m)] = out.get((emp, dept, 'trip', m), Decimal(0)) + daily * count
    return out


def bonus_percent(case, head, on):
    years = Decimal((month_end(on) - case['employees'][head]).days) / Decimal('365.25')
    return [p for bound, p in SCALE if years >= bound][-1]


def bsl_date(d):
    return 'Дата(%d,%d,%d)' % (d.year, d.month, d.day)


def seniority_values(start, unit):
    """Initial seniority at the start of accounting in the declared unit (whole units)."""
    if start >= ACCOUNTING_START:
        return 0
    if unit == 'days':
        return (ACCOUNTING_START - start).days
    months = (ACCOUNTING_START.year - start.year) * 12 + ACCOUNTING_START.month - start.month
    return months if unit == 'months' else months // 12


def report_seniority_range(start, period, unit):
    """Conservative numeric bounds for the reported month, including whole units.

    The ticket does not fix the date in the month or rounding convention. The
    output unit is explicitly declared for the report, not inferred from the
    separate unit of the bonus scale.
    """
    if unit not in ('years', 'months', 'days'):
        raise ValueError('Report seniority unit is not declared or supported')
    divisor = {'years': Decimal('365.25'), 'months': Decimal('30.4375'), 'days': Decimal(1)}[unit]
    lower = Decimal((period - start).days) / divisor
    upper = Decimal((month_end(period) - start).days) / divisor
    return (lower.to_integral_value(rounding='ROUND_FLOOR'),
            upper.to_integral_value(rounding='ROUND_CEILING'))


def code(binding, case, helpers):
    pr = binding['pr']
    obj, f = pr['objects'], pr['fields']
    s = 'Функция Run() Экспорт\nАвтозаполнено = Новый Массив; Подр = Новый Соответствие; Сотр = Новый Соответствие;\n'
    s += 'Снимки = Новый Структура; Проведено = Новый Структура; Ошибки = Новый Структура;\n'
    for dept in case['departments']:
        s += f'Эл = {manager(obj["departments"])}.СоздатьЭлемент(); Эл.Наименование = {q("BENCH_" + dept)}; Эл.УстановитьНовыйКод(); ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать(); Подр.Вставить({q(dept)}, Эл.Ссылка);\n'
    ef = f['employees']
    for emp, start in case['employees'].items():
        s += f'Эл = {manager(obj["employees"])}.СоздатьЭлемент(); Эл.Наименование = {q("BENCH_" + emp)}; Эл.УстановитьНовыйКод();'
        if 'initial_seniority' in ef:
            s += f' Эл.{ef["seniority_start"]} = {bsl_date(max(start, ACCOUNTING_START))}; Эл.{ef["initial_seniority"]} = {seniority_values(start, pr["initial_unit"])};'
        else:
            s += f' Эл.{ef["seniority_start"]} = {bsl_date(start)};'
        s += f' ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать(); Сотр.Вставить({q(emp)}, Эл.Ссылка);\n'
    # Schedules: one record set per department over the whole scenario range.
    sf = f['schedules']
    name = obj['schedules'].split('.', 1)[1]
    s += 'Попытка\n'
    for dept in case['departments']:
        if dept in case.get('unscheduled', ''):
            continue
        s += f'Набор = РегистрыСведений.{name}.СоздатьНаборЗаписей(); Набор.Отбор.{sf["department"]}.Установить(Подр[{q(dept)}]);\n'
        for d in days(SCHEDULE_FROM, SCHEDULE_TO):
            h = hours(dept, d)
            s += f'З = Набор.Добавить(); З.{sf["department"]} = Подр[{q(dept)}]; З.{sf["date"]} = {bsl_date(d)}; З.{sf["hours"]} = {h};'
            s += (f' З.{sf["days"]} = {1 if h else 0};' if sf.get('days') else '') + '\n'
        s += 'Набор.Записать();\n'
    s += 'Исключение Ошибки.Вставить("schedules", ОписаниеОшибки()); КонецПопытки;\n'
    rf = f['rates']
    for emp, since, rate in case['rates']:
        for dept in (case['departments'] if rf.get('department') else [None]):
            values = [(rf['employee'], f'Сотр[{q(emp)}]'), (rf['rate'], str(rate))] + ([(rf['department'], f'Подр[{q(dept)}]')] if dept else [])
            s += register_write(obj['rates'], bsl_date(since), values)
    scf = f['scale']
    s += 'Попытка\n'
    for bound, pct in SCALE:
        s += register_write(obj['scale'], bsl_date(ACCOUNTING_START), [(scf['threshold'], str(bound * (12 if pr['scale_unit'] == 'months' else 1))), (scf['percent'], str(pct))])
    s += 'Исключение Ошибки.Вставить("scale", ОписаниеОшибки()); КонецПопытки;\n'
    reports = {}
    for step in case['steps']:
        if step[0] == 'doc':
            s += doc_code(step, pr, obj, f)
        elif step[0] == 'report':
            report = (binding.get('reports') or {}).get('pr_bonus')
            if not report:
                s += f'Ошибки.Вставить({q(step[1])}, "not_declared");\n'
                continue
            reports['pr_bonus'] = report
            s += f'Попытка СхемаОтчета = Новый Структура; Снимки.Вставить({q(step[1])}, Report_pr_bonus({bsl_date(step[2])}, КонецДня({bsl_date(month_end(step[2]))}), СхемаОтчета)); Снимки.Вставить({q(step[1] + "_schema")}, СхемаОтчета); Исключение Ошибки.Вставить({q(step[1])}, ОписаниеОшибки()); КонецПопытки;\n'
    s += 'Попытка Снимки.Вставить("results", Results()); Исключение Ошибки.Вставить("results", ОписаниеОшибки()); КонецПопытки;\n'
    s += 'Возврат Новый Структура("snapshots,posted,errors,autofilled", Снимки, Проведено, Ошибки, Автозаполнено);\nКонецФункции\n'
    from .report_observability import report_code_with_schema
    for role, report in reports.items():
        s += report_code_with_schema(report, 'Report_' + role)
    return s + results_code(pr) + helpers


def doc_code(step, pr, obj, f):
    _, label, when, rows, _ = step
    af = f['accrual']
    table = af['employee'].split('.')[0]
    sets = pr.get('set', {}).get('accrual', {})
    lines = []
    for kind, emp, dept, start, end in rows:
        line = [(af['employee'].split('.')[1], f'Сотр[{q(emp)}]'), (af['department'].split('.')[1], f'Подр[{q(dept)}]'),
                (af['calc_type'].split('.')[1], 'ПланыВидовРасчета.' + '.'.join(pr['calc_types'][kind].split('.')[1:])),
                (af['start'].split('.')[1], bsl_date(start)), (af['end'].split('.')[1], bsl_date(end))]
        reg = af.get('registration')
        if reg and '.' in reg:
            line.append((reg.split('.')[1], bsl_date(month(start))))
        lines.append(line)
    header = []
    reg = af.get('registration')
    if reg and '.' not in reg:
        header.append((reg, bsl_date(month(rows[0][3]))))
    body = document_code('Док', obj['accrual'], bsl_date(when) .replace(')', ',12,0,0)'), header, {table: lines}, sets)
    return (f'Попытка\n{body}Док.Записать(РежимЗаписиДокумента.Проведение); Проведено.Вставить({q(label)}, Док.Ссылка.ПолучитьОбъект().Проведен);\n'
            f'Исключение Проведено.Вставить({q(label)}, Ложь); Ошибки.Вставить({q(label)}, ОписаниеОшибки()); КонецПопытки;\n')


def results_code(pr):
    """Results of every declared calculation register by employee, department, calculation type and month."""
    s = 'Функция Results()\n Роли = Новый Соответствие;\n'
    for role, ref in pr['calc_types'].items():
        s += f' Роли.Вставить(ПланыВидовРасчета.{".".join(ref.split(".")[1:])}, {q(role)});\n'
    s += ' Итог = Новый ТаблицаЗначений; Для Каждого К Из СтрРазделить("employee,department,role,month,amount", ",") Цикл Итог.Колонки.Добавить(К); КонецЦикла;\n'
    for r in pr['results']:
        name = r['register'].split('.', 1)[1]
        cols = f'Т.{r["employee"]} КАК employee, Т.{r["department"]} КАК department, Т.ВидРасчета КАК kind, СУММА(Т.{r["result"]}) КАК amount'
        tail = f' ИЗ РегистрРасчета.{name} КАК Т ГДЕ Т.Активность СГРУППИРОВАТЬ ПО Т.{r["employee"]}, Т.{r["department"]}, Т.ВидРасчета, '
        by_action = f'ВЫБРАТЬ {cols}, НАЧАЛОПЕРИОДА(Т.ПериодДействияНачало, МЕСЯЦ) КАК month{tail}НАЧАЛОПЕРИОДА(Т.ПериодДействияНачало, МЕСЯЦ)'
        by_registration = f'ВЫБРАТЬ {cols}, НАЧАЛОПЕРИОДА(Т.ПериодРегистрации, МЕСЯЦ) КАК month{tail}НАЧАЛОПЕРИОДА(Т.ПериодРегистрации, МЕСЯЦ)'
        s += f' Текст = ?(Метаданные.РегистрыРасчета.{name}.ПериодДействия, {q(by_action)}, {q(by_registration)});\n'
        s += ' Запрос = Новый Запрос(Текст); Таблица = Запрос.Выполнить().Выгрузить();\n'
        s += (' Для Каждого Стр Из Таблица Цикл Роль = Роли.Получить(Стр.kind); Если Роль = Неопределено Тогда Продолжить; КонецЕсли;\n'
              '  Н = Итог.Добавить(); Н.employee = Строка(Стр.employee); Н.department = Строка(Стр.department); Н.role = Роль; Н.month = Формат(Стр.month, "ДФ=yyyy-MM"); Н.amount = ЧислоИлиНоль(Стр.amount);\n'
              ' КонецЦикла;\n')
    # Sorted by text: calculation-type references differ between infobases, so their order is not repeatable.
    s += ' Итог.Сортировать("employee, department, role, month"); Массив = Новый Массив;\n'
    s += ' Для Каждого Н Из Итог Цикл Массив.Добавить(Новый Структура("employee,department,role,month,amount", Н.employee, Н.department, Н.role, Н.month, Н.amount)); КонецЦикла;\n'
    return s + ' Возврат Массив;\nКонецФункции\n'


def static_signs(src, binding):
    """Q09: recalculation objects in metadata or code; periodicity of the declared rates register."""
    src = Path(src)
    recalc = [p.stem for p in src.glob('CalculationRegisters/*/Recalculations/*.xml')]
    for path in src.rglob('*.bsl'):
        for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
            code = line.split('//', 1)[0]
            if re.search(r'\.Перерасчеты\b|\.Recalculations\b|РегистрыРасчета\.\w+\.Перерасчеты', code):
                recalc.append(path.relative_to(src).as_posix())
                break
    periodicity = None
    ref = ((binding.get('pr') or {}).get('objects') or {}).get('rates', '')
    if ref.startswith('InformationRegister.'):
        path = src / 'InformationRegisters' / (ref.split('.', 1)[1] + '.xml')
        if path.is_file():
            m = re.search(r'<InformationRegisterPeriodicity>(\w+)<', path.read_text(encoding='utf-8-sig'))
            periodicity = m.group(1) if m else None
    return {'recalculation_signs': sorted(set(recalc)), 'rates_periodicity': periodicity}


TOLERANCE = Decimal('0.1')


def compare(observations, binding, static=None):
    """Verdicts for the payroll rules against the reference model; missing observations make a rule inconclusive."""
    static = static or {}
    why = []

    def got(case, emp, dept, role, m=None):
        o = observations[case]
        # The stand could not set up its own data: nothing to judge.
        for setup in ('schedules', 'scale') if role == 'bonus' else ('schedules',):
            if setup in o['errors']:
                raise ValueError('%s could not be written: %s' % (setup, str(o['errors'][setup])[:150]))
        if 'results' in o['errors']:
            raise ValueError('results could not be read: ' + str(o['errors']['results'])[:150])
        return sum((Decimal(str(r['amount'])) for r in o['snapshots']['results'] if r['employee'] == 'BENCH_' + emp and r['department'] == 'BENCH_' + dept
                    and r['role'] == role and (m is None or r['month'] == m.strftime('%Y-%m'))), Decimal(0))

    def expect(case, emp, dept, role, m=None):
        e = model(CASES[case])
        return sum((v for (ee, dd, rr, mm), v in e.items() if ee == emp and dd == dept and rr == role and (m is None or mm == m)), Decimal(0))

    def same(case, emp, dept, role, m=None):
        a, b = got(case, emp, dept, role, m), expect(case, emp, dept, role, m)
        if abs(a - b) > TOLERANCE:
            why.append('%s %s/%s %s%s: %s, expected %s' % (case, emp, dept, role, ' ' + m.strftime('%Y-%m') if m else '', a, b.quantize(Decimal('0.01'))))
            return False
        return True

    def trip_paid_right(case):
        """Trip amount by either reading of the daily rate (owner decision: both accepted)."""
        a = got(case, 'E4', 'B', 'trip')
        one = expect(case, 'E4', 'B', 'trip')
        two = sum((v for (e, d, r, m), v in trip_by_month(CASES[case]).items() if e == 'E4' and d == 'B'), Decimal(0))
        if abs(a - one) <= TOLERANCE or abs(a - two) <= TOLERANCE:
            return True
        why.append('%s E4/B trip: %s, expected %s (one rate for the trip) or %s (own rate in each month)'
                   % (case, a, one.quantize(Decimal('0.01')), two.quantize(Decimal('0.01'))))
        return False

    def trip_cause(case):
        """Why the trip amount is wrong (owner decision 2026-10-13): None if right, 'days' when it equals the amount of
        days counted by the calendar (weekdays or all days) with the right rate months, 'rate' when it equals the amount
        of shifted rate months with the schedule days, otherwise 'unknown' - one defect, charged once under PR11."""
        a = got(case, 'E4', 'B', 'trip')

        def amounts(trip_day=None, previous=(3, 2, 1), data=None):
            data = data or CASES[case]
            one = sum((v for (e, d, r, m), v in model(data, trip_day, previous).items() if e == 'E4' and d == 'B' and r == 'trip'), Decimal(0))
            two = sum((v for (e, d, r, m), v in trip_by_month(data, trip_day, previous).items() if e == 'E4' and d == 'B'), Decimal(0))
            return one, two
        if trip_paid_right(case):
            return None
        hit = lambda values: any(abs(a - v) <= TOLERANCE for v in values)
        if any(hit(amounts(day)) for day in (lambda dept, d: d.weekday() < 5, lambda dept, d: True)):
            why.append('trip days counted by the calendar, not by the department schedule')
            return 'days'
        # A wrong window containing the current month can only read accruals
        # already posted when the trip is entered. Later payroll documents need
        # not recompute it, so check both that prefix and the final ledger.
        data = CASES[case]
        trip_index = next(i for i, step in enumerate(data['steps'])
                          if step[0] == 'doc' and any(row[0] == 'trip' for row in step[3]))
        at_posting = dict(data, steps=data['steps'][:trip_index + 1])
        if any(hit(amounts(previous=p, data=ledger))
               for p in ((2, 1, 0), (1,)) for ledger in (data, at_posting)):
            why.append('daily rate taken from other months than the three previous ones')
            return 'rate'
        return 'unknown'

    def posted(case, label):
        p = observations[case]['posted'].get(label)
        if p is not True:
            why.append('%s: document %s not posted%s' % (case, label, ': ' + str(observations[case]['errors'].get(label, ''))[:150] if label in observations[case]['errors'] else ''))
        return p is True

    def all_posted(case):
        return all([posted(case, s[1]) for s in CASES[case]['steps'] if s[0] == 'doc' and s[4]])

    jan, feb, mar = D(2025, 1, 1), D(2025, 2, 1), D(2025, 3, 1)

    def displaced(case):
        """Tariffs of January and February reduced by the trip days; the trip amount itself is judged by Т4.11-Т4.12."""
        return all_posted(case) & same(case, 'E4', 'B', 'tariff', jan) & same(case, 'E4', 'B', 'tariff', feb)

    def trip_paid():
        if not got('pr_trip', 'E4', 'B', 'trip'):
            why.append('pr_trip: no trip result')
            return False
        return True

    def order_independent():
        """A back-dated trip gives the solution's own result of the in-order entry."""
        a, b = got('pr_backdate', 'E4', 'B', 'trip'), got('pr_trip', 'E4', 'B', 'trip')
        if abs(a - b) > TOLERANCE or not a:
            why.append('trip entered back-dated: %s, entered in order: %s' % (a, b))
            return False
        return True

    def bonus(head, dept):
        return posted('pr_bonus', 'feb') and same('pr_bonus', head, dept, 'bonus', feb)

    def report_ok():
        o = observations['pr_bonus']
        from .report_observability import require_report_fields
        report = (binding.get('reports') or {}).get('pr_bonus')
        fields = report.get('fields') if report else None
        rows = o['snapshots'].get('report_feb')
        required = ['employee', 'amount', 'percent']
        require_report_fields(fields, required, rows, o['snapshots'].get('report_feb_schema'), o['errors'].get('report_feb'))
        ok = True
        matches = {}
        for head, dept in (('H', 'A'), ('G', 'B'), ('K', 'C')):
            amount = expect('pr_bonus', head, dept, 'bonus', feb)
            pct = bonus_percent(CASES['pr_bonus'], head, feb)
            mine = [r for r in rows if str(r.get('employee') or '') == 'BENCH_' + head]

            def num(v):
                try:
                    return Decimal(str(v)) if v not in (None, '') else None
                except Exception:
                    return None
            matches[head] = [r for r in mine if num(r.get('amount')) is not None and abs(num(r.get('amount')) - amount) <= TOLERANCE and ('percent' not in required or num(r.get('percent')) == pct)]
            if not matches[head]:
                why.append('report_feb %s: expected amount %s, percent %s; rows %s' % (head, amount.quantize(Decimal('0.01')), pct, mine[:3]))
                ok = False
        if not ok:
            return False
        require_report_fields(fields, ['seniority'], rows, o['snapshots'].get('report_feb_schema'), o['errors'].get('report_feb'))
        unit = report.get('seniority_unit')
        if unit not in ('years', 'months', 'days'):
            raise ValueError('Report seniority unit is not declared or supported')
        for head, _ in (('H', 'A'), ('G', 'B'), ('K', 'C')):
            lo, hi = report_seniority_range(CASES['pr_bonus']['employees'][head], feb, unit)
            values = [r.get('seniority') for r in matches[head]]
            parsed = [num(value) for value in values]
            if any(v is not None and v.is_finite() and lo <= v <= hi for v in parsed):
                continue
            if any(value not in (None, '') and (number is None or not number.is_finite()) for value, number in zip(values, parsed)):
                raise ValueError('Report seniority value is not a supported number')
            why.append('report_feb %s: seniority outside %s–%s %s' % (head, lo, hi, unit))
            return False
        return True

    checks = {
        'PR01': lambda: displaced('pr_trip'),
        'PR02': lambda: posted('pr_tariff', 'mixed') & same('pr_tariff', 'E1', 'A', 'tariff', jan) & same('pr_tariff', 'E1', 'B', 'tariff', jan),
        'PR03': lambda: posted('pr_tariff', 'mixed') & same('pr_tariff', 'E1', 'B', 'tariff', jan) & same('pr_tariff', 'E1', 'A', 'tariff', jan),
        'PR04': lambda: posted('pr_tariff', 'mixed') & same('pr_tariff', 'E1', 'A', 'tariff', jan) & same('pr_tariff', 'E1', 'A', 'tariff', mar),
        # Б4.3.3-Б4.3.4 ask for a stored history changing at most once a day: the periodicity of the rates register.
        'PR05': lambda: periodicity_ok(),
        'PR06': lambda: posted('pr_tariff', 'mixed') & same('pr_tariff', 'E1', 'A', 'tariff', jan) & same('pr_tariff', 'E1', 'B', 'tariff', jan),
        'PR07': lambda: bonus('H', 'A') & bonus('K', 'C'),
        'PR08': lambda: bonus('H', 'A') & bonus('K', 'C'),
        'PR09': lambda: bonus('H', 'A'),
        'PR10': lambda: displaced('pr_trip') & bonus('G', 'B'),
        'PR11': lambda: posted('pr_trip', 'trip') and trip_cause('pr_trip') in (None, 'rate'),
        # An unexplained wrong amount is one defect, already charged under PR11: PR12 is then not judged separately.
        'PR12': lambda: posted('pr_trip', 'trip') and ({None: True, 'days': True, 'rate': False}.get(trip_cause('pr_trip'))),
        'PR13': lambda: displaced('pr_backdate') & order_independent(),
        # Metadata and textual signs do not prove use on an operative path (A08).
        # Until the observer provides runtime evidence, retain explicit incomplete coverage.
        'PR14': lambda: None if static.get('recalculation_signs') else True,
        'PR15': lambda: all_posted('pr_tariff') & all_posted('pr_bonus') & same('pr_bonus', 'W1', 'A', 'tariff', feb),
        'PR16': lambda: (observations['pr_tariff']['posted'].get('span') is False or why.append('a tariff row 10.03-03.04 was accepted') or False)
                        & posted('pr_tariff', 'part') & same('pr_tariff', 'E1', 'A', 'tariff', mar),
        'PR17': lambda: posted('pr_trip', 'trip') & same('pr_trip', 'E4', 'B', 'tariff', jan) & same('pr_trip', 'E4', 'B', 'tariff', feb) & trip_paid(),
        'PR18': lambda: posted('pr_tariff', 'mixed') & same('pr_tariff', 'E1', 'A', 'tariff', jan) & same('pr_tariff', 'E1', 'A', 'tariff', feb),
        'PR19': report_ok,
    }

    def periodicity_ok():
        if static.get('rates_periodicity') != 'Day':
            why.append('rates register periodicity is %s, Day expected (Q02)' % static.get('rates_periodicity'))
            return False
        return True
    out = []
    for rule, check_ in checks.items():
        why.clear()
        try:
            result = check_()
            verdict = 'inconclusive' if result is None else 'pass' if result else 'fail'
            reason = '; '.join(why)[:600] if verdict == 'fail' and why else None
            if verdict == 'inconclusive':
                reason = ('Recalculation objects/code signs exist, but runtime use is not established (A08).'
                          if rule == 'PR14' else 'Trip amount wrong for an undetermined reason; the defect is charged once under PR11. ' + '; '.join(why)[:400])
        except (KeyError, TypeError, ValueError) as exc:
            verdict, reason = 'inconclusive', 'Required observations unavailable: ' + str(exc)[:200]
        coverage = 'no_violation_found' if rule == 'PR14' and verdict == 'pass' else 'selected_fixture'
        out.append({'id': rule, 'verdict': verdict, 'reason': reason, 'coverage': coverage, 'assertion_id': rule + '.selected_fixture'})
    return out
