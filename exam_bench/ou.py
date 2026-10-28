"""Operational accounting (ticket section Б2): binding check, step scenarios, observer code and verdicts.

The solver declares its operational objects in binding["ou"]. Scenarios are sequences of steps (departments,
policies, specifications, documents, stock snapshots). Stock is read from the declared balance register grouped
by department, item and property, so the verdict does not depend on how batches are stored.
"""
import re
from decimal import Decimal
from pathlib import Path

IDENT = re.compile(r'^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*$')
GROUP = {'Catalog': 'Справочники', 'Document': 'Документы', 'InformationRegister': 'РегистрыСведений',
         'AccumulationRegister': 'РегистрыНакопления', 'ChartOfCharacteristicTypes': 'ПланыВидовХарактеристик'}
OBJECTS = {'departments': 'Catalog', 'properties': 'Catalog', 'policies': 'InformationRegister', 'specification': 'InformationRegister',
           'stock': 'AccumulationRegister', 'receipt': 'Document', 'sale': 'Document', 'assembly': 'Document',
           'characteristics': 'ChartOfCharacteristicTypes', 'property_values': 'InformationRegister'}
FIELDS = {'policies': ('department', 'method'), 'specification': ('block', 'item', 'property', 'quantity'),
          'stock': ('department', 'item', 'property', 'quantity', 'cost'),
          'receipt': ('department', 'item', 'property', 'quantity', 'price', 'amount'),
          'sale': ('department', 'item', 'quantity', 'price', 'amount'),
          'assembly': ('source', 'target', 'block', 'block_quantity', 'extra_item', 'extra_property', 'extra_quantity'),
          'property_values': ('property', 'characteristic', 'value')}
REQUIRED_FIELDS = {'stock': ('department', 'item', 'quantity', 'cost')}


def check(src, ou):
    """Declared operational objects exist and every field is an identifier path; returns True or raises ValueError."""
    from .submission import descriptor
    if not isinstance(ou, dict):
        raise ValueError('binding.ou must be an object')
    for role, ref in ou.get('objects', {}).items():
        if role not in OBJECTS or not isinstance(ref, str) or not ref.startswith(OBJECTS[role] + '.'):
            raise ValueError('ou.objects.%s must be %s.<name>' % (role, OBJECTS.get(role, '?')))
        descriptor(Path(src), ref)
    for role in ('departments', 'policies', 'stock', 'receipt', 'sale'):
        if role not in ou.get('objects', {}):
            raise ValueError('ou.objects.%s is required' % role)
    for role, fields in ou.get('fields', {}).items():
        if role == 'policy_values':
            if set(fields) - {'fifo', 'lifo', 'average'} or not all(isinstance(v, str) and v.startswith('Enum.') for v in fields.values()):
                raise ValueError('ou.fields.policy_values maps fifo/lifo/average to Enum.<name>.<value>')
            continue
        if role == 'properties':
            continue
        if role not in FIELDS or set(fields) - set(FIELDS[role]):
            raise ValueError('Unknown ou.fields role or field: ' + role)
        for path in fields.values():
            if not all(IDENT.fullmatch(p) for p in str(path).split('.')) or str(path).count('.') > 1:
                raise ValueError('ou.fields paths are <attribute> or <table>.<attribute>: ' + str(path))
    for role, need in REQUIRED_FIELDS.items():
        if set(need) - set(ou.get('fields', {}).get(role, {})):
            raise ValueError('ou.fields.%s needs %s' % (role, ', '.join(need)))
    return True


def q(s):
    return '"' + str(s).replace('"', '""') + '"'


def literal(value):
    if isinstance(value, bool):
        return 'Истина' if value else 'Ложь'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and value.startswith('Enum.'):
        return 'Перечисления.' + '.'.join(value.split('.')[1:])
    return q(value)


def manager(ref):
    kind, name = ref.split('.', 1)
    return GROUP[kind] + '.' + name


def date(d):
    y, m, dd = d.split('-')
    return 'Дата(%d,%d,%d,12,0,0)' % (int(y), int(m), int(dd))


# Scenarios: lists of steps. Items: X (peripheral), A and B (details), K (block). Properties belong to details.
CASES = {
    # Same receipts in three departments with FIFO / LIFO / average; one sale document with three department rows.
    'ou_policies': {'departments': ['F', 'L', 'M'], 'items': ['X'], 'properties': {},
                    'steps': [('policy', 'F', 'fifo', '2025-01-01'), ('policy', 'L', 'lifo', '2025-01-01'), ('policy', 'M', 'average', '2025-01-01')]
                    + [('receipt', 'r%s%d' % (dpt, n), d, dpt, [('X', None, qty, price)]) for dpt in 'FLM'
                       for n, (d, qty, price) in enumerate([('2025-01-10', 2, 10), ('2025-01-20', 3, 20)])]
                    + [('snapshot', 'before'), ('sale', 'sale', '2025-01-25', [('F', 'X', 3, 30), ('L', 'X', 3, 30), ('M', 'X', 3, 30)]), ('snapshot', 'after')]},
    # Assembly S->D of 2 K (spec 2A(P1)+B(Q1)) plus extra A(P1)=1; other property P2 and department Z must stay untouched.
    'ou_assembly': {'departments': ['S', 'Z', 'D'], 'items': ['A', 'B', 'K'], 'properties': {'P1': 'A', 'P2': 'A', 'Q1': 'B'},
                    'steps': [('policy', d, 'fifo', '2025-01-01') for d in 'SZD']
                    + [('receipt', 'rS', '2025-01-10', 'S', [('A', 'P1', 10, 10), ('B', 'Q1', 10, 30), ('A', 'P2', 10, 70)]),
                       ('receipt', 'rZ', '2025-01-10', 'Z', [('A', 'P1', 10, 90)]),
                       ('spec', 'K', 'A', 'P1', 2, '2025-01-01'), ('spec', 'K', 'B', 'Q1', 1, '2025-01-01'), ('spec_read', 'spec', '2025-01-20', 'K'),
                       ('snapshot', 'before'), ('assembly', 'asm', '2025-01-20', 'S', 'D', [('K', 2)], [('A', 'P1', 1)]), ('snapshot', 'after')]},
    # Same with the extra detail entered as two rows of 1: rows are summed.
    'ou_assembly_split': {'departments': ['S', 'Z', 'D'], 'items': ['A', 'B', 'K'], 'properties': {'P1': 'A', 'P2': 'A', 'Q1': 'B'},
                          'steps': [('policy', d, 'fifo', '2025-01-01') for d in 'SZD']
                          + [('receipt', 'rS', '2025-01-10', 'S', [('A', 'P1', 10, 10), ('B', 'Q1', 10, 30), ('A', 'P2', 10, 70)]),
                             ('spec', 'K', 'A', 'P1', 2, '2025-01-01'), ('spec', 'K', 'B', 'Q1', 1, '2025-01-01'),
                             ('snapshot', 'before'), ('assembly', 'asm', '2025-01-20', 'S', 'D', [('K', 2)], [('A', 'P1', 1), ('A', 'P1', 1)]), ('snapshot', 'after')]},
    # Policy FIFO from 2023, LIFO from 2025; specification of K: A=1 from 2025-01-01, A=2 from 2025-02-01 (calendar periods, Q02; document date, Q03).
    'ou_history': {'departments': ['H'], 'items': ['X', 'A', 'K'], 'properties': {'P1': 'A'},
                   'steps': [('policy', 'H', 'fifo', '2023-01-01'), ('policy', 'H', 'lifo', '2025-01-01'),
                             ('receipt', 'r23a', '2023-06-01', 'H', [('X', None, 2, 10)]), ('receipt', 'r23b', '2023-06-02', 'H', [('X', None, 3, 20)]),
                             ('snapshot', 's23a'), ('sale', 'sale23', '2023-06-10', [('H', 'X', 1, 30)]), ('snapshot', 's23b'),
                             ('receipt', 'r25', '2025-01-10', 'H', [('X', None, 1, 30)]),
                             ('snapshot', 's25a'), ('sale', 'sale25', '2025-01-20', [('H', 'X', 1, 30)]), ('snapshot', 's25b'),
                             ('spec', 'K', 'A', 'P1', 1, '2025-01-01'), ('spec', 'K', 'A', 'P1', 2, '2025-02-01'),
                             ('spec_read', 'spec_jan', '2025-01-20', 'K'), ('spec_read', 'spec_feb', '2025-02-03', 'K'),
                             ('receipt', 'rA', '2025-01-05', 'H', [('A', 'P1', 10, 10)]),
                             ('snapshot', 'a0'), ('assembly', 'asm_jan', '2025-01-15', 'H', 'H', [('K', 1)], []), ('snapshot', 'a1'),
                             ('assembly', 'asm_feb', '2025-02-03', 'H', 'H', [('K', 1)], []), ('snapshot', 'a2')]},
    # Reports (Q01: the stand chooses the period). Department D, January 2025: X opening 2/20, receipt 3/60, sale 3 (FIFO cost 40,
    # revenue 90); detail A with properties P1 (Manufacturer Alpha) 1/100 and P2 (Beta) 2/120. Department Z and February must stay out.
    'ou_report': {'departments': ['D', 'Z'], 'items': ['X', 'A'], 'properties': {'P1': 'A', 'P2': 'A'},
                  'steps': [('policy', 'D', 'fifo', '2024-01-01'), ('policy', 'Z', 'fifo', '2024-01-01'),
                            ('characteristic', 'Производитель'), ('property_value', 'P1', 'Alpha'), ('property_value', 'P2', 'Beta'), ('props_read', 'props'),
                            ('receipt', 'rDec', '2024-12-10', 'D', [('X', None, 2, 10)]),
                            ('receipt', 'rJan', '2025-01-10', 'D', [('X', None, 3, 20), ('A', 'P1', 1, 100), ('A', 'P2', 2, 60)]),
                            ('receipt', 'rZ', '2025-01-12', 'Z', [('X', None, 5, 7)]),
                            ('sale', 'sJan', '2025-01-20', [('D', 'X', 3, 30)]),
                            ('receipt', 'rFeb', '2025-02-05', 'D', [('X', None, 1, 1)]), ('sale', 'sFeb', '2025-02-10', [('D', 'X', 1, 30)]),
                            ('report', 'statement', 'ou_statement', '2025-01-01', '2025-01-31', 'D'), ('report', 'sales', 'ou_sales', '2025-01-01', '2025-01-31', None)]},
}

RULES = {'OU02': 'policies of three departments in one base', 'OU14': 'sale rows carry department, block or peripheral and quantity',
         'OU15': 'FIFO expense and remainder', 'OU16': 'LIFO expense and remainder', 'OU17': 'average expense and remainder',
         'OU18': 'one document with rows of three departments gives three independent results',
         'OU01': 'receipt, assembly and sale documents post and change stock', 'OU03': 'policy history applies by date (2023 FIFO, 2025 LIFO)',
         'OU05': 'two properties of one detail are counted separately', 'OU06': 'no disassembly object found (Q09: signs only)',
         'OU07': 'specification is stored and read back', 'OU08': 'specification versions dated apart are both available',
         'OU09': 'assembly has two tables: blocks and extra details', 'OU10': 'details from the source department, blocks into the target',
         'OU11': 'consumption = specification x blocks + extra details (rows summed)', 'OU12': 'assembly uses the specification valid on the document date',
         'OU13': 'cost of consumed details by department, detail and property',
         'OU04': 'details are described by characteristics of a chart of characteristic types', 'OU19': 'statement for a department and period',
         'OU20': 'statement grouped by characteristic values', 'OU21': 'sales report: quantity, cost, revenue, profit = revenue - cost'}


def code(binding, case, helpers):
    ou = binding['ou']
    obj = ou['objects']
    f = ou.get('fields', {})
    items_ref = binding['objects']['items']
    article = binding.get('fields', {}).get('items', {}).get('article')
    s = 'Функция Run() Экспорт\nАвтозаполнено = Новый Массив; Подр = Новый Соответствие; Товары = Новый Соответствие; Свойства = Новый Соответствие;\n'
    s += 'Снимки = Новый Структура; Проведено = Новый Структура; Ошибки = Новый Структура;\n'
    for name in case['departments']:
        s += f'Эл = {manager(obj["departments"])}.СоздатьЭлемент(); Эл.Наименование = {q("BENCH_" + name)}; Эл.УстановитьНовыйКод(); Эл.Записать(); Подр.Вставить({q(name)}, Эл.Ссылка);\n'
    for name in case['items']:
        s += f'Эл = {manager(items_ref)}.СоздатьЭлемент(); Эл.Наименование = {q("BENCH_" + name)}; Эл.УстановитьНовыйКод();'
        if article:
            s += f' Эл.{article} = {q("OU-" + name)};'
        s += f' ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать(); Товары.Вставить({q(name)}, Эл.Ссылка);\n'
    owner = ou.get('fields', {}).get('properties', {}).get('owner')
    for name, item in case['properties'].items():
        s += f'Эл = {manager(obj["properties"])}.СоздатьЭлемент(); Эл.Наименование = {q("BENCH_" + name)}; Эл.УстановитьНовыйКод();'
        if owner:
            s += f' Эл.{owner} = Товары[{q(item)}];'
        s += f' ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать(); Свойства.Вставить({q(name)}, Эл.Ссылка);\n'
    reports = {}
    for step in case['steps']:
        if step[0] in ('characteristic', 'property_value', 'props_read') and not ('characteristics' in obj and 'property_values' in obj):
            s += f'Ошибки.Вставить({q(step[0])}, "not_declared");\n'
            continue
        if step[0] == 'report':
            report = (binding.get('reports') or {}).get(step[2])
            if not report:
                s += f'Ошибки.Вставить({q(step[1])}, "not_declared");\n'
                continue
            reports[step[2]] = report
        s += step_code(step, ou, obj, f)
    s += 'Возврат Новый Структура("snapshots,posted,errors,autofilled", Снимки, Проведено, Ошибки, Автозаполнено);\nКонецФункции\n'
    from .grader import report_code
    for role, report in reports.items():
        s += report_code(report, 'Report_' + role, department=role == 'ou_statement')
    if 'characteristics' in obj and 'property_values' in obj:
        s += ou_characteristic_code(obj['characteristics'], obj['property_values'], f['property_values']['value'])
    s += snapshot_code(obj, f) + helpers
    return s


def characteristic_code(ref):
    """A characteristic kind and its values: elements of the additional-values catalog if the chart has one, otherwise strings."""
    name = ref.split('.', 1)[1]
    return f'''Функция НовыйВидХарактеристики(Наименование, Автозаполнено)
 МД = Метаданные.ПланыВидовХарактеристик.{name};
 Х = ПланыВидовХарактеристик.{name}.СоздатьЭлемент(); Х.Наименование = Наименование;
 Если МД.ДополнительныеЗначенияХарактеристик <> Неопределено Тогда
  Х.ТипЗначения = Новый ОписаниеТипов("СправочникСсылка." + МД.ДополнительныеЗначенияХарактеристик.Имя);
 Иначе
  Х.ТипЗначения = Новый ОписаниеТипов("Строка", , Новый КвалификаторыСтроки(10));
 КонецЕсли;
 ЗаполнитьОбязательные(Х, Неопределено, Неопределено, Автозаполнено); Х.Записать();
 Возврат Х.Ссылка;
КонецФункции
Функция ЗначениеХарактеристики(Вид, Текст, Автозаполнено)
 МД = Метаданные.ПланыВидовХарактеристик.{name}.ДополнительныеЗначенияХарактеристик;
 Если МД = Неопределено Тогда Возврат Текст; КонецЕсли;
 Эл = Справочники[МД.Имя].СоздатьЭлемент(); Эл.Владелец = Вид; Эл.Наименование = Текст;
 ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать();
 Возврат Эл.Ссылка;
КонецФункции
'''



def ou_characteristic_code(ref, values_ref, value_field):
    """Use a type supported by both the chart and the bound register value field."""
    name = ref.split('.', 1)[1]
    register = values_ref.split('.', 1)[1]
    field = q(value_field)
    return f'''Функция НовыйВидХарактеристики(Наименование, Автозаполнено)
 МД = Метаданные.ПланыВидовХарактеристик.{name};
 РегистрМД = Метаданные.РегистрыСведений.{register};
 ПолеМД = РегистрМД.Ресурсы.Найти({field});
 Если ПолеМД = Неопределено Тогда ПолеМД = РегистрМД.Измерения.Найти({field}); КонецЕсли;
 Если ПолеМД = Неопределено Тогда ПолеМД = РегистрМД.Реквизиты.Найти({field}); КонецЕсли;
 Если ПолеМД = Неопределено Тогда ВызватьИсключение "Не найдено поле значения характеристики"; КонецЕсли;
 Х = ПланыВидовХарактеристик.{name}.СоздатьЭлемент(); Х.Наименование = Наименование;
 СтрокаПодходит = МД.Тип.СодержитТип(Тип("Строка")) И ПолеМД.Тип.СодержитТип(Тип("Строка"));
 Если СтрокаПодходит Тогда
  Для Каждого Образец Из СтрРазделить("Alpha,Beta", ",") Цикл
   Если МД.Тип.ПривестиЗначение(Образец) <> Образец Или ПолеМД.Тип.ПривестиЗначение(Образец) <> Образец Тогда
    СтрокаПодходит = Ложь;
   КонецЕсли;
  КонецЦикла;
 КонецЕсли;
 Если СтрокаПодходит Тогда
  Х.ТипЗначения = Новый ОписаниеТипов("Строка", , МД.Тип.КвалификаторыСтроки);
 ИначеЕсли МД.ДополнительныеЗначенияХарактеристик <> Неопределено Тогда
  ТипСсылки = Тип("СправочникСсылка." + МД.ДополнительныеЗначенияХарактеристик.Имя);
  Если Не МД.Тип.СодержитТип(ТипСсылки) Или Не ПолеМД.Тип.СодержитТип(ТипСсылки) Тогда
   ВызватьИсключение "Нет поддерживаемого типа значения характеристики";
  КонецЕсли;
  Х.ТипЗначения = Новый ОписаниеТипов("СправочникСсылка." + МД.ДополнительныеЗначенияХарактеристик.Имя);
 Иначе
  ВызватьИсключение "Нет поддерживаемого типа значения характеристики";
 КонецЕсли;
 ЗаполнитьОбязательные(Х, Неопределено, Неопределено, Автозаполнено); Х.Записать();
 Возврат Х.Ссылка;
КонецФункции
Функция ЗначениеХарактеристики(Вид, Текст, Автозаполнено)
 Если Вид.ТипЗначения.СодержитТип(Тип("Строка")) Тогда Возврат Текст; КонецЕсли;
 МД = Метаданные.ПланыВидовХарактеристик.{name}.ДополнительныеЗначенияХарактеристик;
 Если МД = Неопределено Тогда ВызватьИсключение "Нет справочника значений характеристики"; КонецЕсли;
 Эл = Справочники[МД.Имя].СоздатьЭлемент();
 Если МД.Владельцы.Количество() > 0 Тогда
  Если Не МД.Владельцы.Содержит(Метаданные.ПланыВидовХарактеристик.{name}) Тогда
   ВызватьИсключение "Справочник значений не подчинён виду характеристики";
  КонецЕсли;
  Эл.Владелец = Вид;
 КонецЕсли;
 Эл.Наименование = Текст; Эл.УстановитьНовыйКод();
 ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать();
 Возврат Эл.Ссылка;
КонецФункции
'''


def register_write(ref, period, values):
    """Write one information register record with a manager; the period is set only for periodic registers."""
    name = ref.split('.', 1)[1]
    s = f'МЗ = РегистрыСведений.{name}.СоздатьМенеджерЗаписи();\n'
    s += f'Если Метаданные.РегистрыСведений.{name}.ПериодичностьРегистраСведений <> Метаданные.СвойстваОбъектов.ПериодичностьРегистраСведений.Непериодический Тогда МЗ.Период = {period}; КонецЕсли;\n'
    s += ''.join(f'МЗ.{k} = {v}; ' for k, v in values) + 'МЗ.Записать();\n'
    return s


def specification_write(ref, period, values):
    """Append a specification without constraining a handler's period normalization."""
    name = ref.split('.', 1)[1]
    s = f'Набор = РегистрыСведений.{name}.СоздатьНаборЗаписей(); СтрЗаписи = Набор.Добавить();\n'
    s += f'Если Метаданные.РегистрыСведений.{name}.ПериодичностьРегистраСведений <> Метаданные.СвойстваОбъектов.ПериодичностьРегистраСведений.Непериодический Тогда СтрЗаписи.Период = {period}; КонецЕсли;\n'
    s += ''.join(f'СтрЗаписи.{k} = {v}; ' for k, v in values) + 'Набор.Записать(Ложь);\n'
    return s


def document_code(var, ref, when, header, rows_by_table, sets):
    s = f'{var} = {manager(ref)}.СоздатьДокумент(); {var}.Дата = {when};\n'
    for attr, value in header:
        s += f'{var}.{attr} = {value};\n'
    for attr, value in sets.items():
        s += f'{var}.{attr} = {literal(value)};\n'
    for table, rows in rows_by_table.items():
        for row in rows:
            s += f'Стр = {var}.{table}.Добавить(); ' + ' '.join(f'Стр.{attr} = {value};' for attr, value in row) + '\n'
        s += f'Для Каждого Стр Из {var}.{table} Цикл ЗаполнитьОбязательные(Неопределено, {var}.Метаданные().ТабличныеЧасти.{table}, Стр, Автозаполнено); КонецЦикла;\n'
    s += f'ЗаполнитьОбязательные({var}, Неопределено, Неопределено, Автозаполнено);\n'
    return s


def split(path):
    return path.split('.') if '.' in path else (None, path)


def step_code(step, ou, obj, f):
    kind = step[0]
    sets = ou.get('set', {})
    if kind == 'policy':
        _, dept, method, when = step
        pf = f['policies']
        return register_write(obj['policies'], date(when), [(pf['department'], f'Подр[{q(dept)}]'), (pf['method'], literal(f['policy_values'][method]))])
    if kind == 'snapshot':
        return f'Снимки.Вставить({q(step[1])}, StockSnapshot());\n'
    if kind == 'receipt':
        _, label, when, dept, lines = step
        rf = f['receipt']
        header, rows = [], {}
        table = rf['item'].split('.')[0]
        dt, da = split(rf['department'])
        if dt is None:
            header.append((da, f'Подр[{q(dept)}]'))
        for item, prop, qty, price in lines:
            row = [(rf['item'].split('.')[1], f'Товары[{q(item)}]'), (rf['quantity'].split('.')[1], str(qty)),
                   (rf['price'].split('.')[1], str(price)), (rf['amount'].split('.')[1], str(qty * price))]
            if dt is not None:
                row.append((da, f'Подр[{q(dept)}]'))
            if prop and rf.get('property'):
                row.append((rf['property'].split('.')[1], f'Свойства[{q(prop)}]'))
            rows.setdefault(table, []).append(row)
        return posted(label, document_code('Док', obj['receipt'], date(when), header, rows, sets.get('receipt', {})))
    if kind == 'sale':
        _, label, when, lines = step
        sf = f['sale']
        table = sf['item'].split('.')[0]
        dt, da = split(sf['department'])
        header = [(da, f'Подр[{q(lines[0][0])}]')] if dt is None else []
        rows = {table: [[(sf['item'].split('.')[1], f'Товары[{q(item)}]'), (sf['quantity'].split('.')[1], str(qty)),
                         (sf['price'].split('.')[1], str(price)), (sf['amount'].split('.')[1], str(qty * price))]
                        + ([(da, f'Подр[{q(dept)}]')] if dt is not None else []) for dept, item, qty, price in lines]}
        return posted(label, document_code('Док', obj['sale'], date(when), header, rows, sets.get('sale', {})))
    if kind == 'spec':
        _, block, item, prop, qty, when = step
        sf = f['specification']
        values = [(sf['block'], f'Товары[{q(block)}]'), (sf['item'], f'Товары[{q(item)}]'), (sf['quantity'], str(qty))]
        if sf.get('property'):
            values.append((sf['property'], f'Свойства[{q(prop)}]'))
        return specification_write(obj['specification'], date(when), values)
    if kind == 'spec_read':
        _, label, when, block = step
        sf = f['specification']
        name = obj['specification'].split('.', 1)[1]
        cols = [('item', sf['item']), ('qty', sf['quantity'])] + ([('property', sf['property'])] if sf.get('property') else [])
        select = 'ВЫБРАТЬ ' + ', '.join(f'С.{field} КАК {role}' for role, field in cols)
        order = f' УПОРЯДОЧИТЬ ПО С.{sf["item"]}' + (f', С.{sf["property"]}' if sf.get('property') else '')
        sliced = f'{select} ИЗ РегистрСведений.{name}.СрезПоследних(&Дата, {sf["block"]} = &Блок) КАК С' + order
        # A non-periodic register has no slice: its only version is read as is.
        plain = f'{select} ИЗ РегистрСведений.{name} КАК С ГДЕ С.{sf["block"]} = &Блок' + order
        s = (f'Попытка\nТекст = ?(Метаданные.РегистрыСведений.{name}.ПериодичностьРегистраСведений = Метаданные.СвойстваОбъектов.ПериодичностьРегистраСведений.Непериодический, {q(plain)}, {q(sliced)});\n'
             f'Запрос = Новый Запрос(Текст); Запрос.УстановитьПараметр("Дата", {date(when)}); Запрос.УстановитьПараметр("Блок", Товары[{q(block)}]);\n')
        s += 'Массив = Новый Массив; Для Каждого Стр Из Запрос.Выполнить().Выгрузить() Цикл Р = Новый Структура;'
        s += ''.join(f' Р.Вставить({q(role)}, {"ЧислоИлиНоль(Стр.qty)" if role == "qty" else "Строка(Стр." + role + ")"});' for role, _ in cols)
        return s + f' Массив.Добавить(Р); КонецЦикла; Снимки.Вставить({q(label)}, Массив);\nИсключение Ошибки.Вставить({q(label)}, ОписаниеОшибки()); КонецПопытки;\n'
    if kind == 'assembly':
        _, label, when, source, target, blocks, extras = step
        af = f['assembly']
        bt, ba = af['block'].split('.'); _, bq = af['block_quantity'].split('.')
        et, ei = af['extra_item'].split('.'); _, eq = af['extra_quantity'].split('.')
        ep = af['extra_property'].split('.')[1] if af.get('extra_property') else None
        rows = {bt: [[(ba, f'Товары[{q(b)}]'), (bq, str(n))] for b, n in blocks]}
        if extras:
            rows.setdefault(et, []).extend([[(ei, f'Товары[{q(i)}]'), (eq, str(n))] + ([(ep, f'Свойства[{q(p)}]')] if ep else []) for i, p, n in extras])
        header = [(af['source'], f'Подр[{q(source)}]'), (af['target'], f'Подр[{q(target)}]')]
        return posted(label, document_code('Док', obj['assembly'], date(when), header, rows, sets.get('assembly', {})))
    if kind == 'characteristic':
        return f'Попытка Вид = НовыйВидХарактеристики({q("BENCH_" + step[1])}, Автозаполнено); Исключение Вид = Неопределено; Ошибки.Вставить("characteristic", ОписаниеОшибки()); КонецПопытки;\n'
    if kind == 'property_value':
        _, prop, text = step
        pv = f['property_values']
        body = register_write(obj['property_values'], date('2024-01-01'), [(pv['property'], f'Свойства[{q(prop)}]'), (pv['characteristic'], 'Вид'),
                                                                          (pv['value'], f'ЗначениеХарактеристики(Вид, {q(text)}, Автозаполнено)')])
        return f'Попытка\n{body}Исключение Ошибки.Вставить({q("value_" + prop)}, ОписаниеОшибки()); КонецПопытки;\n'
    if kind == 'props_read':
        pv = f['property_values']
        name = obj['property_values'].split('.', 1)[1]
        query = f'ВЫБРАТЬ З.{pv["property"]} КАК property, З.{pv["characteristic"]} КАК characteristic, З.{pv["value"]} КАК value ИЗ РегистрСведений.{name} КАК З УПОРЯДОЧИТЬ ПО З.{pv["property"]}, З.{pv["characteristic"]}'
        return (f'Попытка Массив = Новый Массив; Запрос = Новый Запрос({q(query)}); Для Каждого Стр Из Запрос.Выполнить().Выгрузить() Цикл '
                'Массив.Добавить(Новый Структура("property,characteristic,value", Строка(Стр.property), Строка(Стр.characteristic), Строка(Стр.value))); КонецЦикла; '
                f'Снимки.Вставить({q(step[1])}, Массив); Исключение Ошибки.Вставить({q(step[1])}, ОписаниеОшибки()); КонецПопытки;\n')
    if kind == 'report':
        _, label, role, start, end, dept = step
        y, m, dd = end.split('-')
        args = f'{date(start).replace(",12,0,0)", ",0,0,0)")}, Дата({int(y)},{int(m)},{int(dd)},23,59,59)' + (f', Подр[{q(dept)}]' if dept else '')
        return f'Попытка Снимки.Вставить({q(label)}, Report_{role}({args})); Исключение Ошибки.Вставить({q(label)}, ОписаниеОшибки()); КонецПопытки;\n'
    raise ValueError('Unknown step ' + kind)


def posted(label, body):
    """Post inside a try: a failing document is recorded, later steps still run."""
    return (f'Попытка\n{body}Док.Записать(РежимЗаписиДокумента.Проведение); Проведено.Вставить({q(label)}, Док.Ссылка.ПолучитьОбъект().Проведен);\n'
            f'Исключение Проведено.Вставить({q(label)}, Ложь); Ошибки.Вставить({q(label)}, ОписаниеОшибки()); КонецПопытки;\n')


def snapshot_code(obj, f):
    sf = f['stock']
    name = obj['stock'].split('.', 1)[1]
    dims = [(role, sf[role]) for role in ('department', 'item', 'property') if sf.get(role)]
    select = ', '.join(f'Т.{field} КАК {role}' for role, field in dims)
    group = ', '.join(f'Т.{field}' for _, field in dims)
    query = (f'ВЫБРАТЬ {select}, СУММА(Т.{sf["quantity"]}Остаток) КАК qty, СУММА(Т.{sf["cost"]}Остаток) КАК cost '
             f'ИЗ РегистрНакопления.{name}.Остатки() КАК Т СГРУППИРОВАТЬ ПО {group} УПОРЯДОЧИТЬ ПО {group}')
    s = f'Функция StockSnapshot()\n Запрос = Новый Запрос({q(query)}); Таблица = Запрос.Выполнить().Выгрузить(); Массив = Новый Массив;\n'
    s += ' Для Каждого Стр Из Таблица Цикл\n  Р = Новый Структура("qty,cost", ЧислоИлиНоль(Стр.qty), ЧислоИлиНоль(Стр.cost));\n'
    s += ''.join(f'  Р.Вставить({q(role)}, Строка(Стр.{role}));\n' for role, _ in dims)
    s += '  Массив.Добавить(Р);\n КонецЦикла;\n Возврат Массив;\nКонецФункции\n'
    return s


def static_signs(src, binding=None):
    """Read declared register periodicity and Q09 disassembly metadata."""
    import xml.etree.ElementTree as ET
    from .submission import descriptor, MD
    names = [p.stem for group in ('Documents', 'DataProcessors') for p in (Path(src) / group).glob('*.xml')]
    objects = ((binding or {}).get('ou') or {}).get('objects') or {}
    periods = {}
    for role in ('policies', 'specification'):
        try:
            ref = objects[role]
            if not isinstance(ref, str) or not ref.startswith('InformationRegister.'):
                raise ValueError('Not an information register')
            node = descriptor(Path(src), ref)
            value = node.findtext(MD + 'Properties/' + MD + 'InformationRegisterPeriodicity')
            periods[role] = value if value in ('Year', 'Quarter', 'Month', 'Day', 'Second', 'Nonperiodical', 'RecorderPosition') else None
        except (KeyError, OSError, ValueError, ET.ParseError):
            periods[role] = None
    return {'disassembly_objects': [n for n in names if re.search(r'разбор|disassembl', n, re.I)], 'periodicity': periods}


def compare(observations, binding, static=None):
    static = static or {}
    """Verdicts for the operational rules from stock snapshots; missing observations make a rule inconclusive."""
    d = lambda x: Decimal(str(x))

    def bal(snapshot, dept, item, prop=''):
        rows = [r for r in snapshot if r.get('department') == 'BENCH_' + dept and r.get('item') == 'BENCH_' + item
                and (r.get('property', '') or '') == (('BENCH_' + prop) if prop else '')]
        return (sum((d(r['qty']) for r in rows), Decimal(0)), sum((d(r['cost']) for r in rows), Decimal(0)))

    def policy(dept, expected_after):
        o = observations['ou_policies']
        return o['posted'].get('sale') is True and bal(o['snapshots']['before'], dept, 'X') == (5, 80) and bal(o['snapshots']['after'], dept, 'X') == expected_after

    sale_rows_static = '.' in binding['ou']['fields']['sale']['department']
    af = binding['ou'].get('fields', {}).get('assembly', {})
    two_tables = bool(af) and af['block'].split('.')[0] != af['extra_item'].split('.')[0]

    def consumed(case, dept, item, prop=''):
        o = observations[case]
        b, a = bal(o['snapshots']['before'], dept, item, prop), bal(o['snapshots']['after'], dept, item, prop)
        return (b[0] - a[0], b[1] - a[1])

    def asm_ok(case):
        return observations[case]['posted'].get('asm') is True

    def history_sale(before, after, expected_cost):
        o = observations['ou_history']
        b, a = bal(o['snapshots'][before], 'H', 'X'), bal(o['snapshots'][after], 'H', 'X')
        return b[0] - a[0] == 1 and b[1] - a[1] == expected_cost

    def history_asm(before, after, expected_qty):
        o = observations['ou_history']
        return bal(o['snapshots'][before], 'H', 'A', 'P1')[0] - bal(o['snapshots'][after], 'H', 'A', 'P1')[0] == expected_qty

    why = []

    def num(v):
        try:
            return d(v) if v not in (None, '') else Decimal(0)
        except Exception:
            return None

    def report_row(label, item, expected, characteristic=None):
        """Some row of the report for the item (and characteristic value) has the expected values; tree totals may repeat rows."""
        o = observations['ou_report']
        # Not declared: the stand cannot observe (inconclusive). Declared but failing: the solution's report is broken (fail).
        if o['errors'].get(label) == 'not_declared':
            raise KeyError('Report not declared in binding.reports')
        if label in o['errors']:
            why.append('Report %s failed: %s' % (label, str(o['errors'][label])[:200]))
            return False
        for r in o['snapshots'][label]:
            if str(r.get('item') or '') != 'BENCH_' + item:
                continue
            if characteristic is not None and characteristic not in str(r.get('characteristic') or ''):
                continue
            if all(num(r.get(k)) == d(v) for k, v in expected.items()):
                return True
        return False

    def declared_characteristics():
        o = binding['ou']['objects']
        if not ('characteristics' in o and 'property_values' in o):
            raise ValueError('ou.objects.characteristics and ou.objects.property_values are not declared')
        report = observations['ou_report']
        errors = {k: v for k, v in report['errors'].items() if k in ('characteristic', 'props') or k.startswith('value_')}
        if errors:
            raise ValueError('characteristic values could not be written: ' + str(errors)[:150])
        rows = report['snapshots']['props']
        actual = sorted((r['property'], r['value']) for r in rows if r['characteristic'] == 'BENCH_Производитель')
        if actual != [('BENCH_P1', 'Alpha'), ('BENCH_P2', 'Beta')]:
            raise ValueError('characteristic fixture values differ from the intended values')
        return True

    statement_qty = {f'{k}_qty' for k in ('opening', 'receipt', 'expense', 'closing')} & set(((binding.get('reports') or {}).get('ou_statement') or {}).get('fields', {}))

    def statement_x():
        expected = {'opening': 20, 'receipt': 60, 'expense': 40, 'closing': 40}
        expected.update({k: v for k, v in {'opening_qty': 2, 'receipt_qty': 3, 'expense_qty': 3, 'closing_qty': 2}.items() if k in statement_qty})
        return report_row('statement', 'X', expected)

    def spec(rows):
        return sorted((r['item'], r.get('property', ''), d(r['qty'])) for r in rows)

    def frequency_period(role, expected, history):
        """Combine proved history and metadata without turning missing data into failure."""
        observed, missing = None, None
        try:
            observed = history()
        except (KeyError, TypeError, ValueError) as exc:
            missing = exc
        if observed is False:
            return False
        period = (static.get('periodicity') or {}).get(role)
        if period is None:
            raise ValueError('не удалось установить периодичность регистра ' + role)
        if period != expected:
            raise ValueError('периодичность регистра %s — %s, ожидается %s; проверка другим способом не исключена' % (role, period, expected))
        if missing is not None:
            raise ValueError('история не подтверждена: ' + str(missing))
        return True
    checks = {
        'OU15': lambda: policy('F', (2, 40)),
        'OU16': lambda: policy('L', (2, 20)),
        'OU17': lambda: policy('M', (2, 32)),
        'OU02': lambda: policy('F', (2, 40)) and policy('L', (2, 20)) and policy('M', (2, 32)),
        'OU18': lambda: policy('F', (2, 40)) and policy('L', (2, 20)) and policy('M', (2, 32)),
        'OU14': lambda: sale_rows_static and observations['ou_policies']['posted'].get('sale') is True,
        'OU01': lambda: observations['ou_policies']['posted'].get('sale') is True and asm_ok('ou_assembly') and observations['ou_assembly']['posted'].get('rS') is True
                        and bal(observations['ou_assembly']['snapshots']['after'], 'D', 'K')[0] == 2,
        'OU03': lambda: frequency_period('policies', 'Year', lambda: history_sale('s23a', 's23b', 10) and history_sale('s25a', 's25b', 30)),
        'OU05': lambda: asm_ok('ou_assembly') and consumed('ou_assembly', 'S', 'A', 'P1')[0] == 5 and bal(observations['ou_assembly']['snapshots']['after'], 'S', 'A', 'P2') == (10, 700),
        'OU06': lambda: not static.get('disassembly_objects'),
        'OU07': lambda: spec(observations['ou_assembly']['snapshots']['spec']) == [('BENCH_A', 'BENCH_P1', d(2)), ('BENCH_B', 'BENCH_Q1', d(1))],
        'OU08': lambda: frequency_period('specification', 'Day', lambda: spec(observations['ou_history']['snapshots']['spec_jan']) == [('BENCH_A', 'BENCH_P1', d(1))] and spec(observations['ou_history']['snapshots']['spec_feb']) == [('BENCH_A', 'BENCH_P1', d(2))]),
        'OU09': lambda: two_tables and asm_ok('ou_assembly'),
        'OU10': lambda: asm_ok('ou_assembly') and bal(observations['ou_assembly']['snapshots']['after'], 'D', 'K')[0] == 2
                        and bal(observations['ou_assembly']['snapshots']['after'], 'Z', 'A', 'P1') == (10, 900) and consumed('ou_assembly', 'D', 'A', 'P1') == (0, 0),
        'OU11': lambda: asm_ok('ou_assembly') and consumed('ou_assembly', 'S', 'A', 'P1')[0] == 5 and consumed('ou_assembly', 'S', 'B', 'Q1')[0] == 2
                        and asm_ok('ou_assembly_split') and consumed('ou_assembly_split', 'S', 'A', 'P1')[0] == 6,
        'OU12': lambda: history_asm('a0', 'a1', 1) and history_asm('a1', 'a2', 2),
        'OU13': lambda: asm_ok('ou_assembly') and consumed('ou_assembly', 'S', 'A', 'P1') == (5, 50) and consumed('ou_assembly', 'S', 'B', 'Q1') == (2, 60),
        'OU04': lambda: declared_characteristics() and sorted((r['property'], r['value']) for r in observations['ou_report']['snapshots']['props']
                                                              if r['characteristic'] == 'BENCH_Производитель') == [('BENCH_P1', 'Alpha'), ('BENCH_P2', 'Beta')],
        'OU19': lambda: statement_x(),
        'OU20': lambda: declared_characteristics() and report_row('statement', 'A', {'receipt': 100, 'closing': 100}, 'Alpha')
                        and report_row('statement', 'A', {'receipt': 120, 'closing': 120}, 'Beta'),
        'OU21': lambda: report_row('sales', 'X', {'quantity': 3, 'cost': 40, 'revenue': 90, 'profit': 50}),
    }
    out = []
    for rule, check in checks.items():
        why.clear()
        try:
            verdict, reason = ('pass' if check() else 'fail'), None
            if verdict == 'fail' and why:
                reason = '; '.join(why)
        except (KeyError, TypeError, ValueError) as exc:
            verdict, reason = 'inconclusive', ('Недостаточно данных: ' if rule in ('OU03', 'OU08') else 'Required observations unavailable: ') + str(exc)[:200]
        coverage = 'no_violation_found' if rule == 'OU06' and verdict == 'pass' else 'history_and_periodicity' if rule in ('OU03', 'OU08') else 'selected_fixture'
        if rule == 'OU03' and verdict == 'pass':
            reason = 'История и годовая периодичность регистра подтверждены.'
        if rule == 'OU08' and verdict == 'pass':
            reason = 'История и дневная периодичность подтверждены; ограничение одной версии в неделю отдельно не проверяется.'
        out.append({'id': rule, 'verdict': verdict, 'reason': reason, 'coverage': coverage, 'assertion_id': rule + '.selected_fixture'})
    return out
