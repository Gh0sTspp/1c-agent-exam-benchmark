"""Trusted actions and direct ledger observations; deterministic Python verdicts."""
import json
from decimal import Decimal
from pathlib import Path
from .common import digest, tree_manifest, write_json
from .observer import inject
from .platform import OneC, PlatformError
from .submission import check_bindings
from . import ou, pr, forms, interface, queries
from .workspaces import case_workspace

PROFILE={'schema_version':1,'id':'technical-v8','rules':['BU01','BU02','BU03','BU04','BU05','BU06','BU07','BU08','BU09','BU10','BU11','BU12','BU13','BU14','BU15','BU16','BU17','OU01','OU02','OU03','OU05','OU06','OU07','OU08','OU09','OU10','OU11','OU12','OU13','OU14','OU15','OU16','OU17','OU18','OU04','OU19','OU20','OU21','PR01','PR02','PR03','PR04','PR05','PR06','PR07','PR08','PR09','PR10','PR11','PR12','PR13','PR14','PR15','PR16','PR17','PR18','PR19','F01','F02','F03','F04','F05','G01','G02','G03'],'whole_ticket_verdict':False,'ui_coverage':False,'rule_coverage':{'BU02':'posting_cost_and_balance_only; report and other readers not checked','BU10':'runtime refusal and all financial-register snapshots','BU12':'shared analog C, posting and nonnegative quantity','BU13':'company mean and warehouse quantities','BU03':'chain A~B~C without a direct link','BU06':'warehouse balances and refusal by warehouse stock','BU07':'receipt postings Dt goods Ct suppliers with quantity, amount and analytics','BU08':'own item before analogs','BU09':'automatic substitution by a shared analog','BU11':'ascending string order of articles (Q05)','BU14':'cost posting Dt profit Ct goods with analytics','BU15':'revenue posting Dt customers Ct profit at sale price','BU01':'manual operation accepts an arbitrary correspondence (customers/profit)','BU04':'articles entered by the user are stored unchanged','BU05':'warehouse is a header attribute of receipt and sale, not a table column','BU16':'declared report for January: requested item with sold item rows, February excluded, document line kept','BU17':'report profit = revenue - cost on each row'},'adversarial_cheating_resistance':False,'startup_hooks':'replaced only in disposable observer copy','cases':['manual','average','oversell','dup_split','dup_over','shared_short','shared_enough','chain','own_first','order','report','ou_policies','ou_assembly','ou_assembly_split','ou_history','ou_report','pr_tariff','pr_trip','pr_backdate','pr_bonus','pr_zero','forms','query_texts']}
PROFILE['cases'].extend(['report_balance_contrast', 'report_sales_cardinality'])
PROFILE['rule_coverage'].update({'OU19': 'department and period; contrasting opening balances and unmatched details',
                                 'OU21': 'sales report values and repeated sale lines'})
PROFILE['rule_coverage'].update(ou.RULES);PROFILE['rule_coverage'].update(pr.RULES);PROFILE['rule_coverage'].update(forms.RULES);PROFILE['rule_coverage'].update(interface.RULES)
CASES={
 'manual':{'receipts':[['A','W1',2,60]],'manual':['A','W1',2,20],'sale':[['A',1,40]],'analogs':[],'free_manual':True},
 'average':{'receipts':[['A','W1',2,20],['A','W2',8,240]],'manual':None,'sale':[['A',1,40]],'analogs':[],'undo':True},
 'oversell':{'receipts':[['A','W1',2,20],['A','W2',8,240]],'manual':None,'sale':[['A',3,40]],'analogs':[]},
 # М4.19: the same item in several lines. dup_split sells 1+1 of what «average» sells as one line of 1 (company mean 26);
 # dup_over sells 2+1 where «oversell» sells 3 at once against 2 on W1: each line fits, the document does not.
 'dup_split':{'receipts':[['A','W1',2,20],['A','W2',8,240]],'manual':None,'sale':[['A',1,40],['A',1,40]],'analogs':[]},
 'dup_over':{'receipts':[['A','W1',2,20],['A','W2',8,240]],'manual':None,'sale':[['A',2,40],['A',1,40]],'analogs':[]},
 'shared_short':{'receipts':[['C','W1',2,60]],'manual':None,'sale':[['A',2,40],['B',1,40]],'analogs':[['A','C'],['B','C']]},
 'shared_enough':{'receipts':[['C','W1',3,90]],'manual':None,'sale':[['A',2,40],['B',1,40]],'analogs':[['A','C'],['B','C']]},
 'chain':{'receipts':[['C','W1',2,60]],'manual':None,'sale':[['A',2,40]],'analogs':[['A','B'],['B','C']]},
 'own_first':{'receipts':[['A','W1',1,30],['C','W1',5,150]],'manual':None,'sale':[['A',2,40]],'analogs':[['A','C']]},
 # Articles "BENCH10" and "BENCH2": ascending string order takes BENCH10 first; numeric-suffix or descending order would take BENCH2 (Q05).
 # January: A=1 at 10 and analog C=1 at 20, sale of A=2; February control sale must stay out of the January report.
 'report':{'receipts':[['A','W1',1,10],['C','W1',1,20]],'manual':None,'sale':[['A',2,40]],'analogs':[['A','C']],'report':'bu_sales',
           'later':{'receipts':[['A','W1',1,10]],'sale':[['A',1,40]]}},
 'order':{'receipts':[['B','W1',1,30],['C','W1',1,30]],'manual':None,'sale':[['A',1,40]],'analogs':[['A','B'],['A','C']],'articles':{'B':'BENCH10','C':'BENCH2'}}}


def quoted(s):return '"'+s.replace('"','""')+'"'


HELPERS_CORE='''Функция SubcontoValue(Стр, Сторона, Вид)
 // A row of the register's main table: subconto values are columns Субконто<side>N with their kinds in ВидСубконто<side>N.
 Для Н = 1 По 10 Цикл
  Попытка Текущий = Стр["ВидСубконто" + Сторона + Формат(Н, "ЧГ=0")]; Исключение Возврат Неопределено; КонецПопытки;
  Если Текущий = Вид Тогда Возврат Стр["Субконто" + Сторона + Формат(Н, "ЧГ=0")]; КонецЕсли;
 КонецЦикла;
 Возврат Неопределено;
КонецФункции
Функция SnapshotAll()
 Результат = Новый Структура;
 Для Каждого Рег Из Метаданные.РегистрыБухгалтерии Цикл
  Результат.Вставить("BU_" + Рег.Имя, RecordsAsStrings("РегистрБухгалтерии." + Рег.Имя));
 КонецЦикла;
 Для Каждого Рег Из Метаданные.РегистрыНакопления Цикл
  Результат.Вставить("AU_" + Рег.Имя, RecordsAsStrings("РегистрНакопления." + Рег.Имя));
 КонецЦикла;
 Возврат Результат;
КонецФункции
// Fixture data only: required attributes the binding does not describe get neutral values, so a
// solution with mandatory fields (counterparty, organisation...) is observed instead of failing on the fixture.
Процедура ЗаполнитьОбязательные(Объект, МетаТаблица, СтрокаТЧ, Автозаполнено)
 Если Объект <> Неопределено Тогда
  Для Каждого Рек Из Объект.Метаданные().Реквизиты Цикл
   Если Рек.ПроверкаЗаполнения = ПроверкаЗаполнения.ВыдаватьОшибку И НЕ ЗначениеЗаполнено(Объект[Рек.Имя]) Тогда
    Объект[Рек.Имя] = НейтральноеЗначение(Рек.Тип); Автозаполнено.Добавить(Объект.Метаданные().Имя + "." + Рек.Имя);
   КонецЕсли;
  КонецЦикла;
 КонецЕсли;
 Если МетаТаблица <> Неопределено Тогда
  Для Каждого Рек Из МетаТаблица.Реквизиты Цикл
   Если Рек.ПроверкаЗаполнения = ПроверкаЗаполнения.ВыдаватьОшибку И НЕ ЗначениеЗаполнено(СтрокаТЧ[Рек.Имя]) Тогда
    СтрокаТЧ[Рек.Имя] = НейтральноеЗначение(Рек.Тип); Автозаполнено.Добавить(МетаТаблица.Имя + "." + Рек.Имя);
   КонецЕсли;
  КонецЦикла;
 КонецЕсли;
КонецПроцедуры
Функция НейтральноеЗначение(ОписаниеТипов)
 Для Каждого Т Из ОписаниеТипов.Типы() Цикл
  Если Т = Тип("Строка") Тогда Возврат "BENCH"; КонецЕсли;
  Если Т = Тип("Дата") Тогда Возврат Дата(2025,1,25); КонецЕсли;
  Мета = Метаданные.НайтиПоТипу(Т);
  Если Мета = Неопределено Тогда Продолжить; КонецЕсли;
  Если Метаданные.Перечисления.Содержит(Мета) И Мета.ЗначенияПеречисления.Количество() > 0 Тогда
   Возврат Перечисления[Мета.Имя][Мета.ЗначенияПеречисления[0].Имя];
  КонецЕсли;
  Если Метаданные.Справочники.Содержит(Мета) Тогда
   Найденный = Справочники[Мета.Имя].НайтиПоНаименованию("BENCH_DEFAULT", Истина);
   Если НЕ Найденный.Пустая() Тогда Возврат Найденный; КонецЕсли;
   Попытка
    Эл = Справочники[Мета.Имя].СоздатьЭлемент(); Эл.Наименование = "BENCH_DEFAULT"; Эл.Записать(); Возврат Эл.Ссылка;
   Исключение
   КонецПопытки;
  КонецЕсли;
 КонецЦикла;
 Возврат Неопределено;
КонецФункции
// A resource is NULL for an account without that accounting flag (e.g. no quantity on suppliers): no quantity.
Функция ЧислоИлиНоль(Значение)
 Возврат ?(Значение = NULL, 0, Значение);
КонецФункции
Функция RecordsAsStrings(Имя)
 Запрос = Новый Запрос("ВЫБРАТЬ * ИЗ " + Имя); Таблица = Запрос.Выполнить().Выгрузить(); Массив = Новый Массив;
 Для Каждого Стр Из Таблица Цикл
  Запись = Новый Структура;
  Для Каждого Кол Из Таблица.Колонки Цикл Запись.Вставить(Кол.Имя, Строка(Стр[Кол.Имя])); КонецЦикла;
  Массив.Добавить(Запись);
 КонецЦикла;
 Возврат Массив;
КонецФункции
'''


REPORT_HELPERS='''Процедура ДобавитьСтроки(Строки, Колонки, Карта, Массив, Родитель)
 Для Каждого Стр Из Строки Цикл
  Р = Новый Структура;
  Унаследовано = Новый Массив;
  Для Каждого КЗ Из Карта Цикл
   Значение = Неопределено;
   Если Колонки.Найти(КЗ.Значение) <> Неопределено Тогда Значение = ЗначениеJSON(Стр[КЗ.Значение]); КонецЕсли;
   // Grouping values of a parent tree row apply to its nested rows (e.g. manufacturer -> item).
   Если (Значение = Неопределено Или Значение = "") И Родитель <> Неопределено И Родитель.Свойство(КЗ.Ключ) Тогда Значение = Родитель[КЗ.Ключ]; Унаследовано.Добавить(КЗ.Ключ); КонецЕсли;
   Р.Вставить(КЗ.Ключ, Значение);
  КонецЦикла;
  Лист = Истина;
  Если ТипЗнч(Стр) = Тип("СтрокаДереваЗначений") Тогда Лист = Стр.Строки.Количество() = 0; КонецЕсли;
  ПустаяСтрока = Истина;
  Для Каждого Колонка Из Колонки Цикл
   ФизическоеЗначение = Стр[Колонка.Имя];
   Если Не (ФизическоеЗначение = NULL Или ФизическоеЗначение = Неопределено) Тогда ПустаяСтрока = Ложь; Прервать; КонецЕсли;
  КонецЦикла;
  Р.Вставить("__leaf", Лист);
  Р.Вставить("__inherited", Унаследовано);
  Р.Вставить("__empty", ПустаяСтрока);
  Массив.Добавить(Р);
  Если ТипЗнч(Стр) = Тип("СтрокаДереваЗначений") Тогда ДобавитьСтроки(Стр.Строки, Колонки, Карта, Массив, Р); КонецЕсли;
 КонецЦикла;
КонецПроцедуры
Функция ЗначениеJSON(Значение)
 Если Значение = NULL Или Значение = Неопределено Тогда Возврат Неопределено; КонецЕсли;
 Если ТипЗнч(Значение) = Тип("Число") Или ТипЗнч(Значение) = Тип("Булево") Тогда Возврат Значение; КонецЕсли;
 Возврат Строка(Значение);
КонецФункции
'''


HELPERS=HELPERS_CORE+REPORT_HELPERS


def report_code(report, name='ReportRows', department=False):
    """Run the solver's declared report for a period (and department) and return rows keyed by stand roles."""
    obj=report['object'].split('.')[1]
    args='Начало, Конец'+(', Подразделение' if department else '')
    if report['kind']=='function':
        call=(f'Отчеты.{obj}.Создать().' if report['module']=='object' else f'Отчеты.{obj}.')+report['function']+f'({args})'
        s=f'Функция {name}({args})\n Коллекция = {call};\n'
    else:
        p=report['parameters']
        s=f'''Функция {name}({args})
 Отчет = Отчеты.{obj}.Создать(); Схема = Отчет.СхемаКомпоновкиДанных;
 Компоновщик = Новый КомпоновщикНастроекКомпоновкиДанных; Компоновщик.Инициализировать(Новый ИсточникДоступныхНастроекКомпоновкиДанных(Схема));
 Компоновщик.ЗагрузитьНастройки(Схема.НастройкиПоУмолчанию); Настройки = Компоновщик.ПолучитьНастройки();
'''
        values=[('period_start','Начало'),('period_end','Конец'),('period','Новый СтандартныйПериод(Начало, Конец)')]+([('department','Подразделение')] if department else [])
        for role,value in values:
            if role in p:s+=f' П = Настройки.ПараметрыДанных.НайтиЗначениеПараметра(Новый ПараметрКомпоновкиДанных({quoted(p[role])})); Если П = Неопределено Тогда ВызватьИсключение {quoted("Report parameter absent: "+p[role])}; КонецЕсли; П.Значение = {value}; П.Использование = Истина;\n'
        s+=''' КомпоновщикМакета = Новый КомпоновщикМакетаКомпоновкиДанных;
 Макет = КомпоновщикМакета.Выполнить(Схема, Настройки, , , Тип("ГенераторМакетаКомпоновкиДанныхДляКоллекцииЗначений"));
 Процессор = Новый ПроцессорКомпоновкиДанных; Процессор.Инициализировать(Макет);
 Коллекция = Новый ДеревоЗначений; Вывод = Новый ПроцессорВыводаРезультатаКомпоновкиДанныхВКоллекциюЗначений; Вывод.УстановитьОбъект(Коллекция); Вывод.Вывести(Процессор);
'''
    s+=' Карта = Новый Соответствие;'+''.join(f' Карта.Вставить({quoted(role)}, {quoted(column)});' for role,column in report['fields'].items())+'\n'
    s+=''' Массив = Новый Массив;
 Если ТипЗнч(Коллекция) = Тип("ДеревоЗначений") Тогда ДобавитьСтроки(Коллекция.Строки, Коллекция.Колонки, Карта, Массив, Неопределено); Иначе ДобавитьСтроки(Коллекция, Коллекция.Колонки, Карта, Массив, Неопределено); КонецЕсли;
 Возврат Массив;
КонецФункции
'''
    return s


def code(binding,case):
    """Contains fixture inputs and observations, never expected numbers/verdicts."""
    b=binding;obj={k:v.split('.')[1] for k,v in b['objects'].items()};f=b['fields'];led=f['ledger'];acc=b['account_codes'];a=b['analogs']
    def side(role):return 'Дт' if role.endswith('_debit') else 'Кт'
    def put(role):
        # A physical field, or a predefined subconto kind '<chart of characteristic types>.<kind>' on the role's side.
        path=led[role]
        return f'Субконто{side(role)}[ПланыВидовХарактеристик.{path}]' if '.' in path else path
    def take(role):
        path=led[role]
        return f'SubcontoValue(Стр, "{side(role)}", ПланыВидовХарактеристик.{path})' if '.' in path else 'Стр.'+path
    def doc(role,item,warehouse,qty,amount,date='2025,1,25,12,0,0'):
        ff=f[role];table=ff['item'].split('.')[0]
        if any(ff[k].split('.')[0]!=table for k in ('quantity','price','amount')):raise ValueError('Document numeric fields must share one table')
        s=f'Объект = Документы.{obj[role]}.СоздатьДокумент(); Объект.Дата = Дата({date}); Объект.{ff["warehouse"]} = Склады[{quoted(warehouse)}];\nСтр = Объект.{table}.Добавить();\n'
        for k,value in [('item',f'Товары[{quoted(item)}]'),('quantity',str(qty)),('price',str(Decimal(str(amount))/Decimal(str(qty)))),('amount',str(amount))]:s+=f'Стр.{ff[k].split(".")[1]} = {value};\n'
        s+='ЗаполнитьОбязательные(Объект, Объект.Метаданные().ТабличныеЧасти.'+table+', Стр, Автозаполнено);\nОбъект.Записать(РежимЗаписиДокумента.Проведение);\n'
        return s
    s='Функция Run() Экспорт\nАвтозаполнено = Новый Массив; Товары = Новый Соответствие; Склады = Новый Соответствие;\n'
    for item in ('A','B','C'):
        s+=f'Эл = Справочники.{obj["items"]}.СоздатьЭлемент(); Эл.Наименование = {quoted("BENCH_"+item)}; Эл.{f["items"]["article"]} = {quoted(case.get("articles",{}).get(item,{"A":"900001","B":"900002","C":"900003"}[item]))}; Эл.Записать(); Товары.Вставить({quoted(item)},Эл.Ссылка);\n'
    s+='Артикулы = Новый Соответствие;\n'+''.join(f'Артикулы.Вставить({quoted("BENCH_"+i)}, Строка(Товары[{quoted(i)}].{f["items"]["article"]}));\n' for i in ('A','B','C'))
    for warehouse in ('W1','W2'):
        s+=f'Эл = Справочники.{obj["warehouses"]}.СоздатьЭлемент(); Эл.УстановитьНовыйКод(); Эл.Наименование = {quoted("BENCH_"+warehouse)}; Эл.Записать(); Склады.Вставить({quoted(warehouse)},Эл.Ссылка);\n'
    for role,account in acc.items():
        s+=f'Если ПланыСчетов.{obj["accounts"]}.НайтиПоКоду({quoted(account)}).Пустая() Тогда ВызватьИсключение {quoted("Missing account role "+role)}; КонецЕсли;\n'
    for left,right in case['analogs']:
        if not a['object'].startswith('InformationRegister.'):
            # Analogs in a tabular section of the item: the pair is one row in the left item's card.
            section,column=a['right'].split('.')
            s+=f'Эл = Товары[{quoted(left)}].ПолучитьОбъект(); Стр = Эл.{section}.Добавить(); Стр.{column} = Товары[{quoted(right)}]; Эл.Записать();\n'
            continue
        s+=f'Набор = РегистрыСведений.{a["object"].split(".")[1]}.СоздатьНаборЗаписей(); Набор.Прочитать(); Св = Набор.Добавить(); Св.{a["left"]} = Товары[{quoted(left)}]; Св.{a["right"]} = Товары[{quoted(right)}]; Набор.Записать();\n'
    for item,warehouse,qty,amount in case['receipts']:s+=doc('receipt',item,warehouse,qty,amount)
    if case['manual']:
        item,warehouse,qty,amount=case['manual']
        s+=f'Операция = Документы.{obj["manual"]}.СоздатьДокумент(); Операция.Дата = Дата(2025,1,25,12,0,0); ЗаполнитьОбязательные(Операция, Неопределено, Неопределено, Автозаполнено); Операция.Записать();\nНабор = Операция.Движения.{obj["ledger"]}; Дв = Набор.Добавить(); Дв.Период = Операция.Дата; Дв.СчетДт = ПланыСчетов.{obj["accounts"]}.НайтиПоКоду({quoted(acc["goods"])}); Дв.СчетКт = ПланыСчетов.{obj["accounts"]}.НайтиПоКоду({quoted(acc["suppliers"])}); Дв.{put("item_debit")} = Товары[{quoted(item)}]; Дв.{put("warehouse_debit")} = Склады[{quoted(warehouse)}]; Дв.{led["quantity_debit"]} = {qty}; Дв.{led["amount"]} = {amount}; Набор.Записать();\n'
    s+='До = Snapshot(); ВсеДо = SnapshotAll();\n'
    ff=f['sale'];table=ff['item'].split('.')[0]
    s+=f'Объект = Документы.{obj["sale"]}.СоздатьДокумент(); Объект.Дата = Дата(2025,1,26,12,0,0); Объект.{ff["warehouse"]} = Склады["W1"];\n'
    for item,qty,price in case['sale']:
        s+=f'Стр = Объект.{table}.Добавить();\n'
        for k,value in [('item',f'Товары[{quoted(item)}]'),('quantity',str(qty)),('price',str(price)),('amount',str(qty*price))]:s+=f'Стр.{ff[k].split(".")[1]} = {value};\n'
    s+='Для Каждого Стр Из Объект.'+table+' Цикл ЗаполнитьОбязательные(Неопределено, Объект.Метаданные().ТабличныеЧасти.'+table+', Стр, Автозаполнено); КонецЦикла; ЗаполнитьОбязательные(Объект, Неопределено, Неопределено, Автозаполнено);\n'
    s+='Объект.Записать(); Ошибка = "";\nПопытка Объект.Записать(РежимЗаписиДокумента.Проведение); Исключение Ошибка = ОписаниеОшибки(); КонецПопытки;\n'
    s+='Сохраненный = Объект.Ссылка.ПолучитьОбъект(); После = Snapshot(); Результат = Новый Структура("before,after,posted,posting_error,all_before,all_after,autofilled", До, После, Сохраненный.Проведен, Ошибка, ВсеДо, SnapshotAll(), Автозаполнено);\n'
    if case.get('undo'):
        # М4.17: unposting the sale must bring every financial register back to the state before it.
        s+='Если Сохраненный.Проведен Тогда\nПопытка Сохраненный.Записать(РежимЗаписиДокумента.ОтменаПроведения); Результат.Вставить("undone_all", SnapshotAll()); Исключение Результат.Вставить("undo_error", ОписаниеОшибки()); КонецПопытки;\nКонецЕсли;\n'
    s+='СтатьиАртикулов = Новый Структура; Для Каждого КЗ Из Артикулы Цикл СтатьиАртикулов.Вставить(КЗ.Ключ, КЗ.Значение); КонецЦикла; Результат.Вставить("articles", СтатьиАртикулов);\n'
    s+='Строки = Новый Массив; Для Каждого С Из Сохраненный.'+table+' Цикл Строки.Добавить(Строка(С.'+ff['item'].split('.')[1]+')); КонецЦикла; Результат.Вставить("sale_lines", Строки);\n'
    if case.get('free_manual'):
        # Arbitrary correspondence (customers/profit) through the manual operation document; a refusal is recorded, not raised.
        s+=f'Свободно = Ложь; ОшибкаСвободной = "";\nПопытка\n Оп = Документы.{obj["manual"]}.СоздатьДокумент(); Оп.Дата = Дата(2025,1,27,12,0,0); ЗаполнитьОбязательные(Оп, Неопределено, Неопределено, Автозаполнено); Оп.Записать();\n Набор = Оп.Движения.{obj["ledger"]}; Дв = Набор.Добавить(); Дв.Период = Оп.Дата; Дв.СчетДт = ПланыСчетов.{obj["accounts"]}.НайтиПоКоду({quoted(acc["customers"])}); Дв.СчетКт = ПланыСчетов.{obj["accounts"]}.НайтиПоКоду({quoted(acc["profit"])}); Дв.{led["amount"]} = 5; Набор.Записать(); Свободно = Истина;\nИсключение ОшибкаСвободной = ОписаниеОшибки(); КонецПопытки;\n'
        s+='Результат.Вставить("free_written", Свободно); Результат.Вставить("free_error", ОшибкаСвободной); Результат.Вставить("after_free", Snapshot());\n'
    if case.get('later'):
        # Control documents outside the report period; their failure must not hide the report.
        s+='Попытка\n'
        for item,warehouse,qty,amount in case['later']['receipts']:s+=doc('receipt',item,warehouse,qty,amount,'2025,2,1,12,0,0')
        s+=f'Позже = Документы.{obj["sale"]}.СоздатьДокумент(); Позже.Дата = Дата(2025,2,2,12,0,0); Позже.{ff["warehouse"]} = Склады["W1"];\n'
        for item,qty,price in case['later']['sale']:
            s+=f'Стр = Позже.{table}.Добавить();\n'+''.join(f'Стр.{ff[k].split(".")[1]} = {v};\n' for k,v in [('item',f'Товары[{quoted(item)}]'),('quantity',str(qty)),('price',str(price)),('amount',str(qty*price))])
        s+='Для Каждого Стр Из Позже.'+table+' Цикл ЗаполнитьОбязательные(Неопределено, Позже.Метаданные().ТабличныеЧасти.'+table+', Стр, Автозаполнено); КонецЦикла; ЗаполнитьОбязательные(Позже, Неопределено, Неопределено, Автозаполнено); Позже.Записать(РежимЗаписиДокумента.Проведение);\n'
        s+='Исключение Результат.Вставить("later_error", ОписаниеОшибки()); КонецПопытки;\n'
    if case.get('report'):
        if (b.get('reports') or {}).get(case['report']):
            s+='Попытка СхемаОтчета = Новый Структура; Результат.Вставить("report_rows", ReportRows(Дата(2025,1,1), КонецДня(Дата(2025,1,31)), СхемаОтчета)); Результат.Вставить("report_schema", СхемаОтчета); Исключение Результат.Вставить("report_error", ОписаниеОшибки()); КонецПопытки;\n'
        else:
            s+='Результат.Вставить("report_error", "not_declared");\n'
    s+='Возврат Результат;\nКонецФункции\n'
    if case.get('report') and (b.get('reports') or {}).get(case['report']):
        from .report_observability import report_code_with_schema
        s+=report_code_with_schema(b['reports'][case['report']])
    # Subconto values and kinds (СубконтоДтN, ВидСубконтоДтN) exist only in the virtual table of movements with subconto.
    table='РегистрБухгалтерии.'+obj['ledger']+('.ДвиженияССубконто' if any('.' in led[k] for k in ('item_debit','item_credit','warehouse_debit','warehouse_credit')) else '')
    s+='Функция Snapshot()\nЗапрос = Новый Запрос('+quoted('ВЫБРАТЬ * ИЗ '+table+' УПОРЯДОЧИТЬ ПО Регистратор, НомерСтроки')+'); Таблица = Запрос.Выполнить().Выгрузить(); Массив = Новый Массив;\nДля Каждого Стр Из Таблица Цикл\nР = Новый Структура;\n'
    for key,expression in [('debit','Стр.СчетДт.Код'),('credit','Стр.СчетКт.Код'),('registrar','Строка(Стр.Регистратор)'),('item_debit','Строка('+take('item_debit')+')'),('item_credit','Строка('+take('item_credit')+')'),('warehouse_debit','Строка('+take('warehouse_debit')+')'),('warehouse_credit','Строка('+take('warehouse_credit')+')'),('qty_debit','ЧислоИлиНоль(Стр.'+led['quantity_debit']+')'),('qty_credit','ЧислоИлиНоль(Стр.'+led['quantity_credit']+')'),('amount','ЧислоИлиНоль(Стр.'+led['amount']+')')]:s+=f'Р.Вставить({quoted(key)}, {expression});\n'
    s+='Массив.Добавить(Р); КонецЦикла; Возврат Массив; КонецФункции\n'
    s+=HELPERS
    return s


def compare(observations,binding,static=None):
    static=static or {}
    def d(x):return Decimal(str(x))
    goods=binding['account_codes']['goods']
    def balance(rows,warehouse=None):
        q=Decimal(0);amount=Decimal(0)
        for r in rows:
            if r['debit']==goods and (warehouse is None or r['warehouse_debit']==warehouse):q+=d(r['qty_debit']);amount+=d(r['amount'])
            if r['credit']==goods and (warehouse is None or r['warehouse_credit']==warehouse):q-=d(r['qty_credit']);amount-=d(r['amount'])
        return q,amount
    def sale_cost(x):return sum((d(r['amount']) for r in x['after'] if r['credit']==goods),Decimal(0))
    def same(x):return not x['posted'] and x['before']==x['after'] and x['all_before']==x['all_after']
    acc=binding['account_codes']
    def new_rows(x):
        # Movements added by the sale: the after-snapshot minus the before-snapshot, as a multiset.
        rest=list(x['after'])
        for r in x['before']:
            if r in rest:rest.remove(r)
        return rest
    def expense(x):
        out={}
        for r in x['after']:
            if r['credit']==goods:out[r['item_credit']]=out.get(r['item_credit'],Decimal(0))+d(r['qty_credit'])
        return out
    def receipts_ok(x):
        rows=sorted((r['item_debit'],r['warehouse_debit'],d(r['qty_debit']),d(r['amount'])) for r in x['before'] if r['debit']==goods)
        return rows==[('BENCH_A','BENCH_W1',d(2),d(20)),('BENCH_A','BENCH_W2',d(8),d(240))] and all(r['credit']==acc['suppliers'] for r in x['before'] if r['debit']==goods)
    def cost_ok(x):
        rows=[r for r in new_rows(x) if r['credit']==goods]
        return len(rows)==1 and rows[0]['debit']==acc['profit'] and rows[0]['item_credit']=='BENCH_A' and rows[0]['warehouse_credit']=='BENCH_W1' and d(rows[0]['qty_credit'])==1 and d(rows[0]['amount'])==26
    def revenue_ok(x):
        rows=[r for r in new_rows(x) if r['debit']==acc['customers']]
        return bool(rows) and all(r['credit']==acc['profit'] for r in rows) and sum((d(r['amount']) for r in rows),Decimal(0))==40
    def report_rows(x, required):
        from .report_observability import require_report_fields
        report=(binding.get('reports') or {}).get('bu_sales')
        fields=report.get('fields') if report else None
        rows=x.get('report_rows')
        error=x.get('report_error')
        if error or not isinstance(rows,list) or not all(isinstance(r,dict) for r in rows):
            require_report_fields(fields,required,rows,x.get('report_schema'),error)
        # A DCS tree includes intermediate totals alongside its detail rows.
        # Older snapshots without the marker cannot reliably distinguish them.
        if any(not isinstance(r.get('__leaf'),bool) for r in rows):
            raise ValueError('Report detail rows cannot be distinguished from grouping totals')
        leaves=[r for r in rows if r['__leaf']]
        require_report_fields(fields,required,leaves,x.get('report_schema'),error)
        selected=[r for r in leaves if r.get('item')=='BENCH_A' and r.get('sold') not in (None,'')]
        for row in selected:
            inherited=row.get('__inherited')
            if not isinstance(inherited,list):
                raise ValueError('Report row inheritance information unavailable')
            if set(required).difference(('item','sold')).intersection(inherited):
                raise ValueError('Report detail values may be inherited from a group total')
        return selected
    def report_ok(x):
        found=report_rows(x,['item','sold','quantity','cost','revenue'])
        if any(r.get(k) in (None,'') for r in found for k in ('quantity','cost','revenue')):return False
        rows={(r['sold'],d(r['quantity']),d(r['cost']),d(r['revenue'])) for r in found}
        return x['posted'] and rows=={('BENCH_A',d(1),d(10),d(40)),('BENCH_C',d(1),d(20),d(40))} and x['sale_lines']==['BENCH_A']
    def profit_ok(x):
        rows=report_rows(x,['item','sold','profit','revenue','cost'])
        return bool(rows) and all(all(r.get(k) not in (None,'') for k in ('profit','revenue','cost')) and d(r['profit'])==d(r['revenue'])-d(r['cost']) for r in rows)
    def free_ok(x):
        return x['free_written'] and any(r['debit']==acc['customers'] and r['credit']==acc['profit'] and d(r['amount'])==5 for r in x['after_free'])
    checks={
      'BU01':lambda:free_ok(observations['manual']),
      'BU04':lambda:observations['order']['articles']=={'BENCH_A':'900001','BENCH_B':'BENCH10','BENCH_C':'BENCH2'},
      # Header warehouse is a property of the documents, so it is judged on the posted receipts, not on the sale's own logic.
      'BU05':lambda:static['warehouse_in_header'] and sorted(r['warehouse_debit'] for r in observations['average']['before'] if r['debit']==goods)==['BENCH_W1','BENCH_W2'],
      'BU16':lambda:report_ok(observations['report']),
      'BU17':lambda:profit_ok(observations['report']),
      'BU02':lambda: observations['manual']['posted'] and balance(observations['manual']['before'])==(d(4),d(80)) and sale_cost(observations['manual'])==d(20) and balance(observations['manual']['after'])==(d(3),d(60)),
      # Refusal must be selective: the same stock with a coverable quantity posts, so a sale that never posts cannot pass.
      'BU10':lambda:same(observations['oversell']) and same(observations['shared_short']) and observations['average']['posted'] and observations['shared_enough']['posted'],
      'BU12':lambda:same(observations['shared_short']) and observations['shared_enough']['posted'] and balance(observations['shared_enough']['after'])[0]==0 and sum((d(r['qty_credit']) for r in observations['shared_enough']['after'] if r['credit']==goods and r['item_credit']=='BENCH_C'),Decimal(0))==3 and all(r['item_credit']=='BENCH_C' for r in observations['shared_enough']['after'] if r['credit']==goods),
      'BU03':lambda:observations['chain']['posted'] and expense(observations['chain'])=={'BENCH_C':d(2)},
      'BU06':lambda:same(observations['oversell']) and observations['average']['posted'] and balance(observations['average']['after'],'BENCH_W1')[0]==1 and balance(observations['average']['after'],'BENCH_W2')[0]==8,
      'BU07':lambda:receipts_ok(observations['average']),
      'BU08':lambda:observations['own_first']['posted'] and expense(observations['own_first'])=={'BENCH_A':d(1),'BENCH_C':d(1)},
      'BU09':lambda:observations['shared_enough']['posted'] and expense(observations['shared_enough'])=={'BENCH_C':d(3)},
      'BU11':lambda:observations['order']['posted'] and expense(observations['order'])=={'BENCH_B':d(1)},
      'BU14':lambda:observations['average']['posted'] and cost_ok(observations['average']),
      'BU15':lambda:observations['average']['posted'] and revenue_ok(observations['average']),
      'BU13':lambda:observations['average']['posted'] and sale_cost(observations['average'])==26 and balance(observations['average']['after'])==(d(9),d(234)) and balance(observations['average']['after'],'BENCH_W1')[0]==1 and balance(observations['average']['after'],'BENCH_W2')[0]==8}
    results=[]
    for rule,check in checks.items():
        try:verdict='pass' if check() else 'fail';reason=None
        except (KeyError,TypeError,ValueError) as exc:verdict='inconclusive';reason='Required observations unavailable: '+str(exc)[:200]
        results.append({'id':rule,'verdict':verdict,'reason':reason,'coverage':'partial' if rule=='BU02' else 'selected_fixture','assertion_id':rule+'.posting_cost_and_balance' if rule=='BU02' else rule+'.selected_fixture'})
    return results


def static_checks(source,binding):
    """Checks on exported metadata, no 1C run: warehouse is a header attribute and no table column has the warehouse type."""
    from .submission import descriptor, MD, V
    wh='cfg:'+binding['objects']['warehouses'].replace('Catalog.','CatalogRef.')
    header=all('.' not in binding['fields'][role]['warehouse'] for role in ('receipt','sale'))
    in_rows=any(wh in {t.text for t in a.findall(MD+'Properties/'+MD+'Type/'+V+'Type')}
                for role in ('receipt','sale') for ts in descriptor(Path(source),binding['objects'][role]).findall(MD+'ChildObjects/'+MD+'TabularSection')
                for a in ts.findall(MD+'ChildObjects/'+MD+'Attribute'))
    return {'warehouse_in_header':header and not in_rows}


def grade(source,binding,starter,binary,evidence,selected_cases=None):
    source=Path(source).resolve();evidence=Path(evidence).resolve();evidence.mkdir(parents=True,exist_ok=False)
    from .submission import strip_extras, canonical_ledger
    binding,ignored_sections=strip_extras(binding)
    binding,expanded_names=canonical_ledger(source,binding)
    check_bindings(source,binding)
    original=tree_manifest(source)
    observations={};errors={}
    # Sections with their own declarative binding: an invalid one leaves only its rules unobserved, not the whole submission.
    sections={}
    for key,module,label in (('ou',ou,'Operational accounting'),('pr',pr,'Periodic calculations'),('forms',forms,'Managed forms'),('interface',interface,'General requirements')):
        reason=label+' not declared in binding.'+key
        if key in binding:
            try:module.check(source,binding[key]);reason=None
            except ValueError as exc:reason='binding.%s is invalid: %s'%(key,str(exc)[:200])
        sections[key]=(module,reason)
    # The query texts case needs no binding: the platform parses every complete query literal of the solution (М4.12).
    names=selected_cases or [*CASES,*(n for module,reason in sections.values() if reason is None for n in module.CASES),queries.CASE]
    for name in names:
        root=evidence/name;root.mkdir()
        try:
            with case_workspace(root) as work:
                adapter=OneC(binary,work/'platform',90)
                module=next((m for m,_ in sections.values() if name in m.CASES),None)
                if name==queries.CASE:trusted=inject(source,work/'observed-src',queries.code(source))
                else:trusted=inject(source,work/'observed-src',module.code(binding,module.CASES[name],HELPERS) if module else code(binding,CASES[name]),module.client_code(binding) if hasattr(module,'client_code') else None)
                adapter.restore(work/'ib',starter);adapter.load(work/'ib',trusted)
                result=work/'observations.json'
                adapter.command(['ENTERPRISE','/F',work/'ib','/C',result],'observe',confined=work)
                if not result.exists():raise ValueError('No observations produced')
                data=json.loads(result.read_text(encoding='utf-8-sig'))
            if 'error' in data:errors[name]={'kind':'observation_error','message':data['error']}
            else:observations[name]=data
        except PlatformError as exc:errors[name]={'kind':'platform_error_unclassified','message':str(exc)}
        except (ValueError,OSError,KeyError) as exc:errors[name]={'kind':'adapter_inconclusive','message':str(exc)}
    if tree_manifest(source)!=original:raise ValueError('Frozen submitted source was modified')
    results=compare(observations,binding,static_checks(source,binding))
    for module,reason in sections.values():
        if reason is None:results+=module.compare(observations,binding,module.static_signs(source,binding))
        else:results+=[{'id':r,'verdict':'inconclusive','reason':reason,'coverage':'selected_fixture','assertion_id':r+'.selected_fixture'} for r in module.RULES]
    from .report_query_checks import integrate as integrate_report_query_checks
    results=integrate_report_query_checks(results,observations,binding,selected_cases)
    report={'profile':PROFILE,'source_manifest':original,'observations':observations,'errors':errors,'rules':results,'whole_ticket':'not_evaluated','ignored_binding_sections':ignored_sections,'expanded_binding_names':expanded_names,'status':'partial_pass' if all(r['verdict']=='pass' for r in results) else 'partial_fail' if any(r['verdict']=='fail' for r in results) else 'inconclusive'}
    write_json(evidence/'grade.json',report)
    return report
