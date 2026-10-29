"""Periodic-calculations part of the calibration solution: schedules by department, rates, bonus scale, payroll register.

A small reference that the grader must accept, plus mutants that must fail the targeted payroll rule. Results are
computed in the posting of the starter document «Начисление зарплаты» with plain queries; it is not an exam reference.
Variant one: seniority start date and a scale in years. Variant two: hire date with initial months, a scale in months,
a registration period column in the document rows.
"""
import uuid
import xml.etree.ElementTree as E
from pathlib import Path

from .calibration_ou import M, V, X, I, _child

PROPS = '''<PasswordMode>false</PasswordMode><Format/><EditFormat/><ToolTip/><MarkNegatives>false</MarkNegatives><Mask/><MultiLine>false</MultiLine>
<ExtendedEdit>false</ExtendedEdit><MinValue xsi:nil="true"/><MaxValue xsi:nil="true"/><FillChecking>DontCheck</FillChecking>
<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems><ChoiceParameterLinks/><ChoiceParameters/><QuickChoice>Auto</QuickChoice>
<CreateOnInput>Auto</CreateOnInput><ChoiceForm/><LinkByType/><ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>'''
TYPES = {'decimal': '<v8:Type>xs:decimal</v8:Type><v8:NumberQualifiers><v8:Digits>15</v8:Digits><v8:FractionDigits>4</v8:FractionDigits><v8:AllowedSign>Any</v8:AllowedSign></v8:NumberQualifiers>',
         'date': '<v8:Type>xs:dateTime</v8:Type><v8:DateQualifiers><v8:DateFractions>Date</v8:DateFractions></v8:DateQualifiers>'}
NS = ('xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:v8="http://v8.1c.ru/8.1/data/core" '
      'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.17"')


def _field(kind, name, typ):
    typ = TYPES.get(typ, f'<v8:Type>{typ}</v8:Type>')
    extra = {'Resource': '<FullTextSearch>Use</FullTextSearch>',
             'Attribute': '<ScheduleLink/><Indexing>DontIndex</Indexing><FullTextSearch>Use</FullTextSearch>',
             'Dimension': '<DenyIncompleteValues>false</DenyIncompleteValues><BaseDimension>false</BaseDimension><ScheduleLink/><Indexing>Index</Indexing><FullTextSearch>Use</FullTextSearch>'}[kind]
    return f'<{kind} uuid="{uuid.uuid4()}"><Properties><Name>{name}</Name><Synonym/><Comment/><Type>{typ}</Type>{PROPS}{extra}</Properties></{kind}>'


def calculation_register(name, chart, dimensions, resources, attributes):
    generated = ''.join(f'<xr:GeneratedType name="{t}.{name}" category="{c}"><xr:TypeId>{uuid.uuid4()}</xr:TypeId><xr:ValueId>{uuid.uuid4()}</xr:ValueId></xr:GeneratedType>'
                        for t, c in (('CalculationRegisterRecord', 'Record'), ('CalculationRegisterManager', 'Manager'), ('CalculationRegisterSelection', 'Selection'),
                                     ('CalculationRegisterList', 'List'), ('CalculationRegisterRecordSet', 'RecordSet'), ('CalculationRegisterRecordKey', 'RecordKey'),
                                     ('RecalculationsManager', 'Recalcs')))
    children = (''.join(_field('Resource', n, t) for n, t in resources) + ''.join(_field('Attribute', n, t) for n, t in attributes)
                + ''.join(_field('Dimension', n, t) for n, t in dimensions))
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<MetaDataObject {NS}>
<CalculationRegister uuid="{uuid.uuid4()}"><InternalInfo>{generated}</InternalInfo>
<Properties><Name>{name}</Name><Synonym/><Comment/><UseStandardCommands>true</UseStandardCommands><DefaultListForm/><AuxiliaryListForm/>
<Periodicity>Month</Periodicity><ActionPeriod>false</ActionPeriod><BasePeriod>false</BasePeriod><Schedule/><ScheduleValue/><ScheduleDate/>
<ChartOfCalculationTypes>ChartOfCalculationTypes.{chart}</ChartOfCalculationTypes><IncludeHelpInContents>false</IncludeHelpInContents>
<DataLockControlMode>Managed</DataLockControlMode><FullTextSearch>DontUse</FullTextSearch><ListPresentation/><ExtendedListPresentation/><Explanation/></Properties>
<ChildObjects>{children}</ChildObjects></CalculationRegister>
</MetaDataObject>
'''


def _date_attribute(attribute, name):
    a = attribute('Attribute', name, 'xs:dateTime')
    t = a.find(M + 'Properties/' + M + 'Type')
    q = E.SubElement(t, V + 'DateQualifiers'); E.SubElement(q, V + 'DateFractions').text = 'Date'
    return a


def build(target, n, variant, mutant, clone, save, attribute):
    """Add payroll objects and code; returns (pr binding, pr_bonus report binding)."""
    from .calibration import make_report
    target = Path(target)
    payroll, schedule, scale = n + 'Payroll', n + 'Schedule', n + 'Scale'
    cfg = target / 'Configuration.xml'
    cfg.write_text(cfg.read_text(encoding='utf-8-sig').replace(
        '</ChildObjects>', f'<InformationRegister>{schedule}</InformationRegister><InformationRegister>{scale}</InformationRegister><CalculationRegister>{payroll}</CalculationRegister></ChildObjects>', 1), encoding='utf-8')

    predefined = target / 'ChartsOfCalculationTypes' / 'ОсновныеНачисления' / 'Ext' / 'Predefined.xml'
    text = predefined.read_text(encoding='utf-8-sig')
    items = ''.join(f'\t<Item id="{uuid.uuid4()}">\n\t\t<Name>{name}</Name>\n\t\t<Code>{code}</Code>\n\t\t<Description>{name}</Description>\n\t\t<ActionPeriodIsBase>false</ActionPeriodIsBase>\n\t</Item>\n'
                    for code, name in ((2, 'Тариф'), (3, 'Премия'), (4, 'Командировка')))
    predefined.write_text(text.replace('</PredefinedData>', items + '</PredefinedData>'), encoding='utf-8')

    if mutant == 'rates_monthly':
        rates = target / 'InformationRegisters' / 'СведенияОСотрудниках.xml'
        rates.write_text(rates.read_text(encoding='utf-8-sig').replace('<InformationRegisterPeriodicity>Day<', '<InformationRegisterPeriodicity>Month<'), encoding='utf-8')
    reg = clone('InformationRegisters', 'ГрафикиРаботы', schedule)
    kids = reg[0].find(M + 'ChildObjects'); dim, res = kids.find(M + 'Dimension'), kids.find(M + 'Resource')
    kids.append(_child(dim, 'Department', 'cfg:CatalogRef.Подразделения'))
    if variant != 'one':
        kids.append(_child(res, 'Days', 'xs:decimal'))
    save(target / 'InformationRegisters' / (schedule + '.xml'), reg)

    reg = clone('InformationRegisters', 'КурсыВалют', scale)
    reg[0].find(M + 'Properties/' + M + 'InformationRegisterPeriodicity').text = 'Nonperiodical'
    kids = reg[0].find(M + 'ChildObjects'); res, dim = kids.find(M + 'Resource'), kids.find(M + 'Dimension'); kids.clear()
    kids.append(_child(res, 'Percent', 'xs:decimal')); kids.append(_child(dim, 'Threshold', 'xs:decimal'))
    for tag in ('FillChecking', 'DenyIncompleteValues'):
        for el in kids.iter(M + tag):
            el.text = 'DontCheck' if tag == 'FillChecking' else 'false'  # the lower bound of the first interval is 0
    save(target / 'InformationRegisters' / (scale + '.xml'), reg)

    people = target / 'Catalogs' / 'ФизическиеЛица.xml'
    doc = E.parse(people).getroot(); children = doc[0].find(M + 'ChildObjects')
    if children is None:
        children = E.SubElement(doc[0], M + 'ChildObjects')
    if variant == 'one':
        children.append(_date_attribute(attribute, 'SeniorityStart'))
    else:
        children.append(_date_attribute(attribute, 'HireDate')); children.append(attribute('Attribute', 'InitialMonths', 'xs:decimal'))
    save(people, doc)

    (target / 'CalculationRegisters').mkdir(exist_ok=True)
    (target / 'CalculationRegisters' / (payroll + '.xml')).write_text(calculation_register(
        payroll, 'ОсновныеНачисления', [('Employee', 'cfg:CatalogRef.ФизическиеЛица'), ('Department', 'cfg:CatalogRef.Подразделения')],
        [('Result', 'decimal'), ('Days', 'decimal')],
        [('DateFrom', 'date'), ('DateTo', 'date'), ('Rate', 'decimal'), ('Percent', 'decimal'), ('Seniority', 'decimal')]), encoding='utf-8')

    path = target / 'Documents' / 'НачислениеЗарплаты.xml'
    doc = E.parse(path).getroot(); o = doc[0]
    if variant != 'one':
        table = o.find(M + 'ChildObjects/' + M + 'TabularSection/' + M + 'ChildObjects')
        table.append(_date_attribute(attribute, 'ПериодРегистрации'))
    records = o.find(M + 'Properties/' + M + 'RegisterRecords')
    E.SubElement(records, X + 'Item', {I + 'type': 'xr:MDObjectRef'}).text = 'CalculationRegister.' + payroll
    save(path, doc)
    module = target / 'Documents' / 'НачислениеЗарплаты' / 'Ext' / 'ObjectModule.bsl'
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(posting(payroll, schedule, scale, variant, mutant), encoding='utf-8')

    query = f'''ВЫБРАТЬ Т.Employee КАК Сотрудник, МАКСИМУМ(Т.Seniority) КАК Стаж, МАКСИМУМ(Т.Percent) КАК Процент, СУММА(Т.Result) КАК Сумма
ИЗ РегистрРасчета.{payroll} КАК Т
ГДЕ Т.ВидРасчета = ЗНАЧЕНИЕ(ПланВидовРасчета.ОсновныеНачисления.Премия) И Т.ПериодРегистрации МЕЖДУ &НачалоПериода И &КонецПериода
СГРУППИРОВАТЬ ПО Т.Employee'''
    if mutant == 'bonus_report_all_months':
        query = query.replace(' И Т.ПериодРегистрации МЕЖДУ &НачалоПериода И &КонецПериода', ' И &НачалоПериода = &НачалоПериода И &КонецПериода = &КонецПериода')
    if mutant == 'bonus_report_wrong_seniority':
        query = query.replace('МАКСИМУМ(Т.Seniority) КАК Стаж', '100 КАК Стаж')
    report = make_report(target, n + 'Bonuses', variant, query, {'employee': 'Сотрудник', 'seniority': 'Стаж', 'percent': 'Процент', 'amount': 'Сумма'},
                         ['Сотрудник', 'Стаж', 'Процент'], ['Сумма'])
    report['seniority_unit'] = 'years' if variant == 'one' else 'months'
    types = {k: 'ChartOfCalculationTypes.ОсновныеНачисления.' + v for k, v in (('tariff', 'Тариф'), ('bonus', 'Премия'), ('trip', 'Командировка'))}
    employees = {'seniority_start': 'SeniorityStart'} if variant == 'one' else {'seniority_start': 'HireDate', 'initial_seniority': 'InitialMonths'}
    pr = {'objects': {'employees': 'Catalog.ФизическиеЛица', 'departments': 'Catalog.Подразделения', 'schedules': 'InformationRegister.' + schedule,
                      'rates': 'InformationRegister.СведенияОСотрудниках', 'scale': 'InformationRegister.' + scale, 'accrual': 'Document.НачислениеЗарплаты'},
          'results': [{'register': 'CalculationRegister.' + payroll, 'employee': 'Employee', 'department': 'Department', 'result': 'Result'}],
          'calc_types': types, 'scale_unit': 'years' if variant == 'one' else 'months',
          'fields': {'schedules': {'department': 'Department', 'date': 'Дата', 'hours': 'Значение', **({} if variant == 'one' else {'days': 'Days'})},
                     'rates': {'employee': 'Сотрудник', 'department': 'Подразделение', 'rate': 'Оклад'},
                     'scale': {'threshold': 'Threshold', 'percent': 'Percent'}, 'employees': employees,
                     'accrual': {'employee': 'ОсновныеНачисления.Сотрудник', 'department': 'ОсновныеНачисления.Подразделение',
                                 'calc_type': 'ОсновныеНачисления.ВидРасчета', 'start': 'ОсновныеНачисления.ДатаНачала', 'end': 'ОсновныеНачисления.ДатаОкончания',
                                 **({} if variant == 'one' else {'registration': 'ОсновныеНачисления.ПериодРегистрации'})}}}
    if variant != 'one':
        pr['initial_unit'] = 'months'
    return pr, report


def posting(payroll, schedule, scale, variant, mutant):
    """Posting of «Начисление зарплаты»: trips, then tariffs, then bonuses; a back-dated trip corrects earlier tariffs."""
    m = lambda name: mutant == name
    rate_query = ('ВЫБРАТЬ ПЕРВЫЕ 1 С.Оклад КАК Ставка ИЗ РегистрСведений.СведенияОСотрудниках КАК С ГДЕ С.Сотрудник = &С И С.Подразделение = &П УПОРЯДОЧИТЬ ПО С.Период'
                  if m('rate_no_history') else
                  'ВЫБРАТЬ С.Оклад КАК Ставка ИЗ РегистрСведений.СведенияОСотрудниках.СрезПоследних(&Дата, Сотрудник = &С И Подразделение = &П) КАК С')
    rate_date = {'rate_at_month_end': 'КонецМесяца(Начало)', 'doc_date_period': 'НачалоМесяца(Дата)'}.get(mutant, 'НачалоМесяца(Начало)')
    schedule_query = (f'ВЫБРАТЬ Г.Дата КАК День, МАКСИМУМ(Г.Значение) КАК Часы ИЗ РегистрСведений.{schedule} КАК Г ГДЕ Г.Дата МЕЖДУ &Н И &К СГРУППИРОВАТЬ ПО Г.Дата'
                      if m('schedule_common') else
                      f'ВЫБРАТЬ Г.Дата КАК День, Г.Значение КАК Часы ИЗ РегистрСведений.{schedule} КАК Г ГДЕ Г.Department = &П И Г.Дата МЕЖДУ &Н И &К')
    period = 'ЗначениеЗаполнено(С.ПериодРегистрации)' if variant != 'one' else 'Ложь'
    if variant == 'one':
        seniority = ('Начало = ' + ('Макс(С.Сотрудник.SeniorityStart, Дата(2025,1,1))' if m('seniority_from_accounting') else 'С.Сотрудник.SeniorityStart') +
                     ';\n Возврат (НачалоДня(КонецМесяца(Расчетный)) - Начало) / 86400 / 365.25;')
    else:
        seniority = ('Начало = С.Сотрудник.HireDate; Конец = КонецМесяца(Расчетный);\n'
                     ' Месяцев = (Год(Конец) - Год(Начало)) * 12 + Месяц(Конец) - Месяц(Начало) - ?(День(Конец) < День(Начало), 1, 0);\n'
                     ' Возврат Месяцев' + ('' if m('seniority_from_accounting') else ' + С.Сотрудник.InitialMonths') + ';')
    percent = ('Возврат ?(Стаж >= ' + ('3' if variant == 'one' else '36') + ', 15, ?(Стаж >= ' + ('1' if variant == 'one' else '12') + ', 10, 5));'
               if m('scale_hardcoded') else
               f'''Запрос = Новый Запрос("ВЫБРАТЬ ПЕРВЫЕ 1 Ш.Percent КАК Процент ИЗ РегистрСведений.{scale} КАК Ш ГДЕ Ш.Threshold <= &Стаж УПОРЯДОЧИТЬ ПО Ш.Threshold УБЫВ");
 Запрос.УстановитьПараметр("Стаж", Стаж); Т = Запрос.Выполнить().Выгрузить();
 Возврат ?(Т.Количество() = 0, 0, Т[0].Процент);''')
    previous = '-2, 0' if m('trip_rate_wrong_months') else '-3, -1'
    trip_day = 'ДеньНедели(День) <= 5' if m('trip_calendar_days') else 'Г.Часы > 0'
    return f'''// Calibration payroll: trips first, then tariffs, then bonuses. Results by registration month of the period they belong to.

Процедура ОбработкаПроведения(Отказ, РежимПроведения)
 Движения.{payroll}.Записывать = Истина;
 Виды = Новый Соответствие;
 Для Каждого С Из ОсновныеНачисления Цикл
  Виды.Вставить(С.ВидРасчета, Истина);
  {'' if m('one_month_unchecked') else 'Если С.ВидРасчета <> ПланыВидовРасчета.ОсновныеНачисления.Командировка И НачалоМесяца(С.ДатаНачала) <> НачалоМесяца(С.ДатаОкончания) Тогда Сообщить("Тариф и премия вводятся в пределах одного месяца"); Отказ = Истина; Возврат; КонецЕсли;'}
  {'Если С.ВидРасчета = ПланыВидовРасчета.ОсновныеНачисления.Командировка И НачалоМесяца(С.ДатаНачала) <> НачалоМесяца(С.ДатаОкончания) Тогда Отказ = Истина; Возврат; КонецЕсли;' if m('cross_month_refused') else ''}
 КонецЦикла;
 {'Если Виды.Количество() > 1 Тогда Отказ = Истина; Возврат; КонецЕсли;' if m('mixed_kinds_refused') else ''}
 {'Если Ложь Тогда Х = РегистрыРасчета.' + payroll + '.Перерасчеты; КонецЕсли;' if m('recalculation_sign') else ''}
 Для Каждого С Из ОсновныеНачисления Цикл Если С.ВидРасчета = ПланыВидовРасчета.ОсновныеНачисления.Командировка Тогда Командировка(С); КонецЕсли; КонецЦикла;
 Для Каждого С Из ОсновныеНачисления Цикл Если С.ВидРасчета = ПланыВидовРасчета.ОсновныеНачисления.Тариф Тогда Тариф(С); КонецЕсли; КонецЦикла;
 Для Каждого С Из ОсновныеНачисления Цикл Если С.ВидРасчета = ПланыВидовРасчета.ОсновныеНачисления.Премия Тогда Премия(С); КонецЕсли; КонецЦикла;
КонецПроцедуры

Функция Период(С)
 Возврат ?({period}, НачалоМесяца(С.ПериодРегистрации), НачалоМесяца(С.ДатаНачала));
КонецФункции

Функция Поездки(Сотрудник)
 Запрос = Новый Запрос("ВЫБРАТЬ Т.ДатаНачала КАК Н, Т.ДатаОкончания КАК К ИЗ Документ.НачислениеЗарплаты.ОсновныеНачисления КАК Т
 |ГДЕ Т.Ссылка.Проведен И Т.Ссылка <> &Ссылка И Т.Сотрудник = &С И Т.ВидРасчета = ЗНАЧЕНИЕ(ПланВидовРасчета.ОсновныеНачисления.Командировка)");
 Запрос.УстановитьПараметр("Ссылка", Ссылка); Запрос.УстановитьПараметр("С", Сотрудник);
 Т = Запрос.Выполнить().Выгрузить();
 Для Каждого С Из ОсновныеНачисления Цикл
  Если С.Сотрудник = Сотрудник И С.ВидРасчета = ПланыВидовРасчета.ОсновныеНачисления.Командировка Тогда Н = Т.Добавить(); Н.Н = С.ДатаНачала; Н.К = С.ДатаОкончания; КонецЕсли;
 КонецЦикла;
 Возврат Т;
КонецФункции

Функция ВПоездке(Т, День)
 Для Каждого П Из Т Цикл Если НачалоДня(П.Н) <= День И День <= НачалоДня(П.К) Тогда Возврат Истина; КонецЕсли; КонецЦикла;
 Возврат Ложь;
КонецФункции

Функция График(Подразделение, Начало, Конец)
 Запрос = Новый Запрос("{schedule_query}");
 Запрос.УстановитьПараметр("П", Подразделение); Запрос.УстановитьПараметр("Н", НачалоДня(Начало)); Запрос.УстановитьПараметр("К", КонецДня(Конец));
 Возврат Запрос.Выполнить().Выгрузить();
КонецФункции

// Tariff for a period inside one month: rate at the start of the month x hours by the department schedule outside trips.
Функция СуммаТарифа(Сотрудник, Подразделение, Начало, Конец, Ставка, Дни)
 Т = Поездки(Сотрудник); Часы = 0; Дни = 0;
 {'Для Каждого Г Из График(Подразделение, НачалоМесяца(Начало), КонецМесяца(Начало)) Цикл Если ВПоездке(Т, НачалоДня(Г.День)) Тогда Возврат 0; КонецЕсли; КонецЦикла;' if m('trip_displaces_whole_month') else ''}
 Для Каждого Г Из График(Подразделение, Начало, Конец) Цикл
  Если Г.Часы > 0 {'' if m('no_displacement') else 'И НЕ ВПоездке(Т, НачалоДня(Г.День))'} Тогда Часы = Часы + Г.Часы; Дни = Дни + 1; КонецЕсли;
 КонецЦикла;
 Запрос = Новый Запрос("{rate_query}");
 Запрос.УстановитьПараметр("С", Сотрудник); Запрос.УстановитьПараметр("П", Подразделение); Запрос.УстановитьПараметр("Дата", {rate_date});
 Р = Запрос.Выполнить().Выгрузить(); Ставка = ?(Р.Количество() = 0, 0, Р[0].Ставка);
 Возврат {'Ставка * Дни' if m('rate_times_days') else 'Ставка * Часы'};
КонецФункции

Процедура Запись(С, Вид, Период, Результат, Дни, Начало, Конец)
 Д = Движения.{payroll}.Добавить(); Д.ПериодРегистрации = Период; Д.ВидРасчета = Вид;
 Д.Employee = С.Сотрудник; Д.Department = {'ОсновныеНачисления.Найти(С.Сотрудник, "Сотрудник").Подразделение' if m('parttime_merged') else 'С.Подразделение'};
 Д.Result = Результат; Д.Days = Дни; Д.DateFrom = Начало; Д.DateTo = Конец;
КонецПроцедуры

Процедура Тариф(С)
 Ставка = 0; Дни = 0; Сумма = СуммаТарифа(С.Сотрудник, С.Подразделение, С.ДатаНачала, С.ДатаОкончания, Ставка, Дни);
 Запись(С, С.ВидРасчета, Период(С), Сумма, Дни, С.ДатаНачала, С.ДатаОкончания);
КонецПроцедуры

// Trip: one daily rate for the whole trip from the three full months before its start, by the sending department.
Процедура Командировка(С)
 Начало = НачалоМесяца(С.ДатаНачала);
 Запрос = Новый Запрос("ВЫБРАТЬ ЕСТЬNULL(СУММА(Т.Result), 0) КАК Сумма, ЕСТЬNULL(СУММА(ВЫБОР КОГДА Т.ВидРасчета = ЗНАЧЕНИЕ(ПланВидовРасчета.ОсновныеНачисления.Тариф) ТОГДА Т.Days ИНАЧЕ 0 КОНЕЦ), 0) КАК Дни
 |ИЗ РегистрРасчета.{payroll} КАК Т ГДЕ Т.Employee = &С И Т.Department = &П И Т.ПериодРегистрации МЕЖДУ &Н И &К");
 Запрос.УстановитьПараметр("С", С.Сотрудник); Запрос.УстановитьПараметр("П", С.Подразделение);
 Запрос.УстановитьПараметр("Н", ДобавитьМесяц(Начало, {previous.split(", ")[0]})); Запрос.УстановитьПараметр("К", ДобавитьМесяц(Начало, {previous.split(", ")[1]}));
 Итог = Запрос.Выполнить().Выгрузить()[0];
 ДневнаяСтавка = ?(Итог.Дни = 0, 0, Итог.Сумма / Итог.Дни);
 ПоМесяцам = Новый Соответствие;
 Для Каждого Г Из График(С.Подразделение, С.ДатаНачала, С.ДатаОкончания) Цикл
  День = Г.День;
  Если {trip_day} Тогда Месяц = НачалоМесяца(День); ПоМесяцам.Вставить(Месяц, ?(ПоМесяцам.Получить(Месяц) = Неопределено, 0, ПоМесяцам.Получить(Месяц)) + 1); КонецЕсли;
 КонецЦикла;
 Для Каждого КЗ Из ПоМесяцам Цикл
  Запись(С, С.ВидРасчета, КЗ.Ключ, Окр(ДневнаяСтавка * КЗ.Значение, 2), 0, С.ДатаНачала, С.ДатаОкончания);
 КонецЦикла;
 {'' if m('no_backdate') else 'Исправить(С);'}
КонецПроцедуры

// Back-dated trip: tariffs already posted for its months are corrected by the difference in the same periods.
Процедура Исправить(С)
 Запрос = Новый Запрос("ВЫБРАТЬ Т.Department КАК Подразделение, Т.DateFrom КАК Н, Т.DateTo КАК К, Т.ПериодРегистрации КАК Период, СУММА(Т.Result) КАК Сумма, СУММА(Т.Days) КАК Дни
 |ИЗ РегистрРасчета.{payroll} КАК Т ГДЕ Т.Employee = &С И Т.ВидРасчета = ЗНАЧЕНИЕ(ПланВидовРасчета.ОсновныеНачисления.Тариф) И Т.DateFrom <= &К И Т.DateTo >= &Н
 |СГРУППИРОВАТЬ ПО Т.Department, Т.DateFrom, Т.DateTo, Т.ПериодРегистрации");
 Запрос.УстановитьПараметр("С", С.Сотрудник); Запрос.УстановитьПараметр("Н", НачалоДня(С.ДатаНачала)); Запрос.УстановитьПараметр("К", КонецДня(С.ДатаОкончания));
 Для Каждого Р Из Запрос.Выполнить().Выгрузить() Цикл
  Ставка = 0; Дни = 0; Нужно = СуммаТарифа(С.Сотрудник, Р.Подразделение, Р.Н, Р.К, Ставка, Дни);
  Если Нужно <> Р.Сумма Тогда
   Д = Движения.{payroll}.Добавить(); Д.ПериодРегистрации = Р.Период; Д.ВидРасчета = ПланыВидовРасчета.ОсновныеНачисления.Тариф;
   Д.Employee = С.Сотрудник; Д.Department = Р.Подразделение; Д.Result = Нужно - Р.Сумма; Д.Days = Дни - Р.Дни; Д.DateFrom = Р.Н; Д.DateTo = Р.К;
  КонецЕсли;
 КонецЦикла;
КонецПроцедуры

Функция РассчитатьСтаж(С, Расчетный)
 {seniority}
КонецФункции

Функция ПроцентПремии(Стаж)
 {percent}
КонецФункции

// Head bonus: percent by seniority of the previous month tariffs of the department without the head, reduced by trip days.
Процедура Премия(С)
 Месяц = Период(С);
 Запрос = Новый Запрос("ВЫБРАТЬ ЕСТЬNULL(СУММА(Т.Result), 0) КАК База ИЗ РегистрРасчета.{payroll} КАК Т
 |ГДЕ Т.Department = &П И Т.ВидРасчета = ЗНАЧЕНИЕ(ПланВидовРасчета.ОсновныеНачисления.Тариф){'' if m('bonus_includes_head') else ' И Т.Employee <> &С'} И Т.ПериодРегистрации = &Месяц");
 Запрос.УстановитьПараметр("П", С.Подразделение); Запрос.УстановитьПараметр("С", С.Сотрудник);
 Запрос.УстановитьПараметр("Месяц", {'Месяц' if m('bonus_current_month') else 'ДобавитьМесяц(Месяц, -1)'});
 База = Запрос.Выполнить().Выгрузить()[0].База;
 Стаж = РассчитатьСтаж(С, Месяц); Процент = ПроцентПремии(Стаж);
 Т = Поездки(С.Сотрудник); План = 0; Факт = 0;
 Для Каждого Г Из График(С.Подразделение, С.ДатаНачала, С.ДатаОкончания) Цикл
  Если Г.Часы > 0 Тогда План = План + 1; Если {'Истина' if m('bonus_not_displaced') else 'НЕ ВПоездке(Т, НачалоДня(Г.День))'} Тогда Факт = Факт + 1; КонецЕсли; КонецЕсли;
 КонецЦикла;
 Д = Движения.{payroll}.Добавить(); Д.ПериодРегистрации = Месяц; Д.ВидРасчета = С.ВидРасчета; Д.Employee = С.Сотрудник; Д.Department = С.Подразделение;
 Д.Result = ?(План = 0, 0, Окр(База * Процент / 100 * Факт / План, 2)); Д.Percent = Процент; Д.Seniority = Стаж; Д.DateFrom = С.ДатаНачала; Д.DateTo = С.ДатаОкончания;
КонецПроцедуры
'''
