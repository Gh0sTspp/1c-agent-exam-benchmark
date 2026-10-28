"""Managed forms (ticket section Б5): binding check, scenario, server and client observer code, verdicts.

The solver declares the counterparty catalog with its manager attribute, the employee catalog with the list of
additional information kinds (a chart of characteristic types) and where counterparty values are stored. The server
part creates kinds, two managers with different lists and counterparties; the client part gets the counterparty main
form without opening it, records its visible fields, fills the additional fields and writes the form.
"""
import re
from pathlib import Path

from .ou import IDENT, manager, q

OBJECTS = {'counterparties': 'Catalog', 'managers': 'Catalog', 'characteristics': 'ChartOfCharacteristicTypes'}
KINDS = {'C1': 'Валюта', 'C2': 'Срок', 'C3': 'Регион'}
LISTS = {'M1': ['C1', 'C2'], 'M2': ['C3']}
COUNTERPARTIES = {'K1': 'M1', 'K2': 'M2'}
TYPED = {'C1': 'USD', 'C2': '15'}

CASES = {'forms': {}}
RULES = {'F01': 'manager field in the counterparty main form', 'F02': 'each employee keeps own list of additional information',
         'F03': 'the list refers to a chart of characteristic types', 'F04': 'additional fields of the selected manager appear in the form',
         'F05': 'values typed into the additional fields are saved'}


def name(key):
    return 'BENCH_' + (KINDS.get(key) or key)


def path(p, table=False):
    parts = str(p).split('.')
    return all(IDENT.fullmatch(x) for x in parts) and len(parts) == (2 if table else 1)


def check(src, forms):
    from .submission import descriptor
    if not isinstance(forms, dict):
        raise ValueError('binding.forms must be an object')
    objects = forms.get('objects', {})
    for role, kind in OBJECTS.items():
        ref = objects.get(role)
        if not isinstance(ref, str) or not ref.startswith(kind + '.'):
            raise ValueError('forms.objects.%s must be %s.<name>' % (role, kind))
        descriptor(Path(src), ref)
    f = forms.get('fields', {})
    if not path(f.get('counterparties', {}).get('manager', '')) or not path(f.get('managers', {}).get('list', ''), table=True):
        raise ValueError('forms.fields: counterparties.manager is <attribute>, managers.list is <table>.<attribute>')
    v = forms.get('values', {})
    if v.get('kind') == 'table':
        if not all(path(v.get(k, ''), table=True) for k in ('characteristic', 'value')):
            raise ValueError('forms.values (table): characteristic and value are <table>.<attribute> of the counterparty')
    elif v.get('kind') == 'register':
        if not str(v.get('register', '')).startswith('InformationRegister.'):
            raise ValueError('forms.values.register must be InformationRegister.<name>')
        descriptor(Path(src), v['register'])
        if not all(path(v.get(k, '')) for k in ('counterparty', 'characteristic', 'value')):
            raise ValueError('forms.values (register): counterparty, characteristic and value fields')
    else:
        raise ValueError('forms.values.kind is table or register')
    form = forms.get('form')
    if form is not None and not re.fullmatch(r'Catalog\.\w+\.Form\.\w+', str(form)):
        raise ValueError('forms.form is Catalog.<name>.Form.<name>')
    return True


def form_name(forms):
    """1C name of the counterparty main form: the declared one or the default object form."""
    if forms.get('form'):
        _, catalog, _, form = forms['form'].split('.')
        return 'Справочник.%s.Форма.%s' % (catalog, form)
    return 'Справочник.%s.ФормаОбъекта' % forms['objects']['counterparties'].split('.', 1)[1]


def code(binding, case, helpers):
    """Server part: kinds, managers with lists, counterparties; exported lookups for the client part."""
    forms = binding['forms']
    obj, f = forms['objects'], forms['fields']
    table, attr = f['managers']['list'].split('.')
    s = 'Функция Run() Экспорт\nАвтозаполнено = Новый Массив; Виды = Новый Соответствие; Менеджеры = Новый Соответствие;\n'
    s += 'Снимки = Новый Структура; Ошибки = Новый Структура;\n'
    s += 'Если Не ВводСтрокПоддерживается() Тогда Возврат Новый Структура("fixture_error", "Контрольные строки USD и 15 не поддерживаются типом характеристики или поля хранения"); КонецЕсли;\n'
    for key in KINDS:
        s += f'Виды.Вставить({q(key)}, НовыйВидХарактеристики({q(name(key))}, Автозаполнено));\n'
    for m, kinds in LISTS.items():
        s += f'Эл = {manager(obj["managers"])}.СоздатьЭлемент(); Эл.Наименование = {q(name(m))}; Эл.УстановитьНовыйКод();\n'
        s += ''.join(f'Стр = Эл.{table}.Добавить(); Стр.{attr} = Виды[{q(k)}];\n' for k in kinds)
        s += f'ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать(); Менеджеры.Вставить({q(m)}, Эл.Ссылка);\n'
    for k, m in COUNTERPARTIES.items():
        s += (f'Эл = {manager(obj["counterparties"])}.СоздатьЭлемент(); Эл.Наименование = {q(name(k))}; Эл.УстановитьНовыйКод(); '
              f'Эл.{f["counterparties"]["manager"]} = Менеджеры[{q(m)}]; ЗаполнитьОбязательные(Эл, Неопределено, Неопределено, Автозаполнено); Эл.Записать();\n')
    mname = obj['managers'].split('.', 1)[1]
    query = f'ВЫБРАТЬ Т.Ссылка.Наименование КАК manager, ПРЕДСТАВЛЕНИЕ(Т.{attr}) КАК kind ИЗ Справочник.{mname}.{table} КАК Т ГДЕ Т.Ссылка.Наименование ПОДОБНО "BENCH_%" УПОРЯДОЧИТЬ ПО Т.Ссылка, Т.НомерСтроки'
    s += f'Запрос = Новый Запрос({q(query)}); Массив = Новый Массив;\n'
    s += 'Для Каждого Стр Из Запрос.Выполнить().Выгрузить() Цикл Массив.Добавить(Новый Структура("manager,kind", Стр.manager, Стр.kind)); КонецЦикла;\n'
    s += 'Снимки.Вставить("lists", Массив);\n'
    s += 'Возврат Новый Структура("snapshots,errors,autofilled", Снимки, Ошибки, Автозаполнено);\nКонецФункции\n'
    s += f'''Функция Ref(Вид, Имя) Экспорт
 Если Вид = "manager" Тогда Возврат {manager(obj["managers"])}.НайтиПоНаименованию(Имя, Истина); КонецЕсли;
 Возврат {manager(obj["counterparties"])}.НайтиПоНаименованию(Имя, Истина);
КонецФункции
'''
    s += stored_code(forms)
    return s + forms_characteristic_code(forms) + helpers


def forms_characteristic_code(forms):
    """Create kinds compatible with the literal values typed by the form observer."""
    chart = forms['objects']['characteristics'].split('.', 1)[1]
    values = forms['values']
    if values['kind'] == 'table':
        catalog = forms['objects']['counterparties'].split('.', 1)[1]
        table, field = values['value'].split('.')
        field_code = (f'ТЧ = Метаданные.Справочники.{catalog}.ТабличныеЧасти.Найти({q(table)});\n'
                      f' Если ТЧ = Неопределено Тогда Возврат Ложь; КонецЕсли;\n'
                      f' ПолеМД = ТЧ.Реквизиты.Найти({q(field)});')
    else:
        register = values['register'].split('.', 1)[1]
        field = q(values['value'])
        field_code = (f'РегистрМД = Метаданные.РегистрыСведений.{register};\n'
                      f' ПолеМД = РегистрМД.Ресурсы.Найти({field});\n'
                      f' Если ПолеМД = Неопределено Тогда ПолеМД = РегистрМД.Измерения.Найти({field}); КонецЕсли;\n'
                      f' Если ПолеМД = Неопределено Тогда ПолеМД = РегистрМД.Реквизиты.Найти({field}); КонецЕсли;')
    return f'''Функция ВводСтрокПоддерживается()
 МД = Метаданные.ПланыВидовХарактеристик.{chart};
 {field_code}
 Если ПолеМД = Неопределено Тогда Возврат Ложь; КонецЕсли;
 Если Не МД.Тип.СодержитТип(Тип("Строка")) Или Не ПолеМД.Тип.СодержитТип(Тип("Строка")) Тогда Возврат Ложь; КонецЕсли;
 Для Каждого Образец Из СтрРазделить("USD,15", ",") Цикл
  Если МД.Тип.ПривестиЗначение(Образец) <> Образец Или ПолеМД.Тип.ПривестиЗначение(Образец) <> Образец Тогда Возврат Ложь; КонецЕсли;
 КонецЦикла;
 Возврат Истина;
КонецФункции
Функция НовыйВидХарактеристики(Наименование, Автозаполнено)
 МД = Метаданные.ПланыВидовХарактеристик.{chart};
 Х = ПланыВидовХарактеристик.{chart}.СоздатьЭлемент(); Х.Наименование = Наименование;
 Х.ТипЗначения = Новый ОписаниеТипов("Строка", , МД.Тип.КвалификаторыСтроки);
 ЗаполнитьОбязательные(Х, Неопределено, Неопределено, Автозаполнено); Х.Записать();
 Возврат Х.Ссылка;
КонецФункции
'''


def stored_code(forms):
    """Exported server function: values stored for a counterparty as (kind, value) strings."""
    v = forms['values']
    cname = forms['objects']['counterparties'].split('.', 1)[1]
    if v['kind'] == 'table':
        table, kind = v['characteristic'].split('.')
        value = v['value'].split('.')[1]
        query = f'ВЫБРАТЬ ПРЕДСТАВЛЕНИЕ(Т.{kind}) КАК kind, Т.{value} КАК value ИЗ Справочник.{cname}.{table} КАК Т ГДЕ Т.Ссылка = &К УПОРЯДОЧИТЬ ПО Т.НомерСтроки'
    else:
        rname = v['register'].split('.', 1)[1]
        query = f'ВЫБРАТЬ ПРЕДСТАВЛЕНИЕ(Т.{v["characteristic"]}) КАК kind, Т.{v["value"]} КАК value ИЗ РегистрСведений.{rname} КАК Т ГДЕ Т.{v["counterparty"]} = &К УПОРЯДОЧИТЬ ПО Т.{v["characteristic"]}'
    return f'''Функция Stored(Имя) Экспорт
 Запрос = Новый Запрос({q(query)}); Запрос.УстановитьПараметр("К", Ref("counterparty", Имя));
 Массив = Новый Массив;
 Для Каждого Стр Из Запрос.Выполнить().Выгрузить() Цикл Массив.Добавить(Новый Структура("kind,value", Стр.kind, Строка(Стр.value))); КонецЦикла;
 Возврат Массив;
КонецФункции
'''


def client_code(binding):
    """Client part, run after the server part: main form fields for each counterparty, then typing and writing."""
    forms = binding['forms']
    form = form_name(forms)
    s = f'''Процедура ClientRun(Результат)
 Если Результат.Свойство("fixture_error") Тогда Возврат; КонецЕсли;
 Формы = Новый Структура;
 Для Каждого Имя Из СтрРазделить("{",".join(COUNTERPARTIES)}", ",") Цикл
  Попытка
   Ф = ПолучитьФорму({q(form)}, Новый Структура("Ключ", BenchmarkObserver.Ref("counterparty", "BENCH_" + Имя)));
   Формы.Вставить(Имя, ПоляФормы(Ф, Ложь));
  Исключение
   Формы.Вставить(Имя, Новый Структура("error", ОписаниеОшибки()));
  КонецПопытки;
 КонецЦикла;
 // Type values into the additional fields of K1 and write the form as a user would.
 Попытка
  Ф = ПолучитьФорму({q(form)}, Новый Структура("Ключ", BenchmarkObserver.Ref("counterparty", {q(name("K1"))})));
  Заполнено = Новый Массив;
  Для Каждого Поле Из ПоляФормы(Ф, Истина).fields Цикл
'''
    for key, value in TYPED.items():
        # The data path of an item is not available on the client: the field is filled through the form attribute of the same name.
        s += (f'   Если Поле.visible И СтрНайти(Поле.title, {q(name(key))}) > 0 Тогда '
              f'Ф[Поле.name] = {q(value)}; Заполнено.Добавить({q(key)}); КонецЕсли;\n')
    s += f'''  КонецЦикла;
  Записано = Ф.Записать();
  Формы.Вставить("saved", Новый Структура("typed,written,stored", Заполнено, Записано, BenchmarkObserver.Stored({q(name("K1"))})));
 Исключение
  Формы.Вставить("saved", Новый Структура("error", ОписаниеОшибки()));
 КонецПопытки;
 Результат.Вставить("forms", Формы);
КонецПроцедуры

// Item names of dynamic fields carry generated ids: kept only for typing, never in observations.
Функция ПоляФормы(Ф, СИменами)
 Поля = Новый Массив;
 Для Каждого Э Из Ф.Элементы Цикл
  Если ТипЗнч(Э) <> Тип("ПолеФормы") Тогда Продолжить; КонецЕсли;
  Видимо = Э.Видимость; Р = Э.Родитель;
  Пока Видимо И ТипЗнч(Р) <> ТипЗнч(Ф) Цикл Видимо = Р.Видимость; Р = Р.Родитель; КонецЦикла;
  Поле = Новый Структура("title,visible", Строка(Э.Заголовок), Видимо);
  Если СИменами Тогда Поле.Вставить("name", Э.Имя); КонецЕсли;
  Поля.Добавить(Поле);
 КонецЦикла;
 Возврат Новый Структура("fields", Поля);
КонецФункции
'''
    return s


def manager_field(src, forms):
    """Visible field with the manager attribute in the main form layout: 'present', 'hidden', 'absent' or 'no_form'."""
    catalog = forms.get('objects', {}).get('counterparties', '').split('.', 1)[-1]
    form = forms.get('form')
    if form:
        form = form.split('.')[-1]
    else:
        meta = Path(src) / 'Catalogs' / (catalog + '.xml')
        m = re.search(r'<DefaultObjectForm>Catalog\.\w+\.Form\.(\w+)</DefaultObjectForm>', meta.read_text(encoding='utf-8-sig')) if meta.is_file() else None
        form = m.group(1) if m else None
    layout = Path(src) / 'Catalogs' / catalog / 'Forms' / str(form) / 'Ext' / 'Form.xml'
    if not form or not layout.is_file():
        return 'no_form'
    text = layout.read_text(encoding='utf-8-sig')
    attr = forms.get('fields', {}).get('counterparties', {}).get('manager', '')
    found = 'absent'
    for item in re.finditer(r'<(InputField|LabelField)\b[^>]*>(.*?)</\1>', text, re.S):
        body = re.sub(r'<ChildItems>.*', '', item.group(2), flags=re.S)
        if re.search(r'<DataPath>(Объект|Object)\.' + re.escape(attr) + r'</DataPath>', body):
            if '<Visible>false</Visible>' in body:
                found = 'hidden'
            else:
                return 'present'
    return found


def static_signs(src, binding):
    """The list attribute of employees refers to the declared chart of characteristic types (Б5.2.2)."""
    forms = binding.get('forms') or {}
    chart = forms.get('objects', {}).get('characteristics', '').split('.', 1)[-1]
    catalog = forms.get('objects', {}).get('managers', '').split('.', 1)[-1]
    table, attr = (forms.get('fields', {}).get('managers', {}).get('list', '.').split('.') + [''])[:2]
    out = {'manager_field': manager_field(src, forms)}
    p = Path(src) / 'Catalogs' / (catalog + '.xml')
    if not p.is_file():
        return dict(out, list_types=None)
    text = p.read_text(encoding='utf-8-sig')
    m = re.search(r'<TabularSection\b.*?<Name>' + re.escape(table) + r'</Name>(.*?)</TabularSection>', text, re.S)
    section = m.group(1) if m else ''
    a = re.search(r'<Attribute\b[^>]*>\s*<Properties>\s*<Name>' + re.escape(attr) + r'</Name>(.*?)</Attribute>', section, re.S)
    types = re.findall(r'<v8:Type>([^<]+)</v8:Type>', a.group(1)) if a else []
    return dict(out, list_types=types, chart=chart)


def compare(observations, binding, static=None):
    static = static or {}
    forms = binding['forms']
    mattr = forms['fields']['counterparties']['manager']
    why = []

    def obs():
        result = observations['forms']
        if result.get('fixture_error'):
            raise ValueError('form fixture unavailable: ' + str(result['fixture_error'])[:150])
        return result

    def fields(key):
        o = obs()
        if 'forms' not in o:
            raise ValueError('client part produced no form observations')
        got = o['forms'].get(key) or {}
        if 'error' in got:
            why.append('form %s could not be obtained: %s' % (key, str(got['error'])[:200]))
            return None
        return got['fields']

    def shown(key):
        f = fields(key)
        if f is None:
            return None
        return {k for k in KINDS if any(x['visible'] and name(k) in x['title'] for x in f)}

    def kinds_ok(key, expected):
        got = shown(key)
        if got is None:
            return False
        if got != set(expected):
            why.append('form %s shows %s, expected %s' % (key, sorted(name(k) for k in got), sorted(name(k) for k in expected)))
            return False
        return True

    def lists():
        got = {}
        for r in obs()['snapshots']['lists']:
            got.setdefault(r['manager'], set()).add(r['kind'])
        expected = {name(m): {name(k) for k in ks} for m, ks in LISTS.items()}
        if got != expected:
            why.append('lists read back %s, expected %s' % ({k: sorted(v) for k, v in got.items()}, {k: sorted(v) for k, v in expected.items()}))
            return False
        return True

    def manager_field():
        state = static.get('manager_field')
        if state != 'present':
            why.append('main form: field Объект.%s is %s' % (mattr, state))
            return False
        return fields('K1') is not None

    def chart_typed():
        types = static.get('list_types')
        if not types or not all(t.endswith('ChartOfCharacteristicTypesRef.' + static.get('chart', '')) for t in types):
            why.append('list attribute type %s, expected a reference to the chart %s' % (types, static.get('chart')))
            return False
        return True

    def saved():
        got = obs()['forms'].get('saved') or {}
        if 'error' in got:
            raise ValueError('form input or write was not confirmed: ' + str(got['error'])[:150])
        typed = got.get('typed')
        if not isinstance(typed, list) or not set(TYPED).issubset(typed):
            raise ValueError('required form fields were not confirmed as entered')
        if got.get('written') is not True:
            raise ValueError('form write was not confirmed')
        stored = {(r['kind'], r['value']) for r in got['stored']}
        expected = {(name(k), v) for k, v in TYPED.items()}
        if not expected <= stored:
            why.append('typed %s, written %s, stored %s' % (got.get('typed'), got.get('written'), sorted(stored)))
            return False
        return True

    checks = {
        'F01': manager_field,
        'F02': lists,
        'F03': lambda: lists() & chart_typed(),
        'F04': lambda: kinds_ok('K1', LISTS['M1']) & kinds_ok('K2', LISTS['M2']),
        'F05': saved,
    }
    out = []
    for rule, check_ in checks.items():
        why.clear()
        try:
            verdict = 'pass' if check_() else 'fail'
            reason = '; '.join(why)[:600] if verdict == 'fail' and why else None
        except (KeyError, TypeError, ValueError) as exc:
            verdict, reason = 'inconclusive', 'Required observations unavailable: ' + str(exc)[:200]
        out.append({'id': rule, 'verdict': verdict, 'reason': reason, 'coverage': 'selected_fixture', 'assertion_id': rule + '.selected_fixture'})
    return out
