import json
import tempfile
import unittest
from pathlib import Path

from exam_bench.penalties import assess, signature

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks/1c-platform-official-sample'


class Penalties(unittest.TestCase):
    def setUp(self):
        self.catalogue = json.loads((TASK / 'private/official-assessment-mapping.json').read_text())
        self.policy = json.loads((TASK / 'private/owner-scoring-policy.json').read_text())
        self.requirements = json.loads((TASK / 'checks.json').read_text())['requirements']
        self.starter = json.loads((ROOT / 'starters/carcass-8.3.25.1445/starter.json').read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name)
        self.config('Managed')
        self.accounts([a['name'] for a in self.starter['predefined_accounts']['accounts']])
        (self.src / 'Reports').mkdir()
        (self.src / 'Reports' / 'R.xml').write_text('<Report/>')
        (self.src / 'Documents').mkdir()
        self.binding = {'objects': {'receipt': 'Document.ПриходнаяНакладная', 'sale': 'Document.РасходнаяНакладная', 'manual': 'Document.Операция'}}

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, mode):
        (self.src / 'Configuration.xml').write_text(f'<Configuration><DataLockControlMode>{mode}</DataLockControlMode></Configuration>')

    def accounts(self, names):
        path = self.src / 'ChartsOfAccounts/Управленческий/Ext/Predefined.xml'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(f'<Item><Name>{n}</Name></Item>' for n in names))

    def run_with(self, rules, observations=None, gates=None):
        return assess(rules, self.src, self.binding, self.requirements, self.starter, self.catalogue, self.policy, gates, observations)

    def bu(self, verdict='pass', **override):
        return [{'id': r['id'], 'verdict': override.get(r['id'], verdict), 'reason': None} for r in self.requirements if r['section'] == 'BU']

    def test_clean_accounting_section_charges_nothing(self):
        result = self.run_with(self.bu())
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['score']['score_upper_bound'], '5')
        self.assertEqual(result['gates']['core_sections'], {'OU': 'not_attested', 'PR': 'not_attested'})
        self.assertEqual(result['score']['attestation'], 'not_attested_required_section_unverifiable')

    def test_each_failed_requirement_is_a_minimum_penalty(self):
        result = self.run_with(self.bu(BU03='fail', BU08='fail'))
        self.assertEqual(sorted(f['defect_id'] for f in result['findings']), ['requirement.BU03', 'requirement.BU08'])
        self.assertEqual(result['score']['deductions'], '1.0')  # 2 x 0.5, the minimum of М4.1

    def test_wrong_report_data_is_not_evidence_of_wrong_report_form(self):
        self.binding.update(ou={'objects': {}}, pr={'objects': {}})
        for requirement in ('OU19', 'OU20', 'OU21', 'BU16', 'BU17', 'PR19'):
            with self.subTest(requirement=requirement):
                section = requirement[:2]
                rules = [{'id': r['id'], 'verdict': 'fail' if r['id'] == requirement else 'pass',
                          'reason': 'ожидаемое и фактическое значение различаются' if r['id'] == requirement else None}
                         for r in self.requirements if r['section'] == section]
                result = self.run_with(rules)
                findings = [(f['penalty_id'], f['defect_id']) for f in result['findings']]
                self.assertIn(('F1C-GEN01', 'requirement.' + requirement), findings)
                self.assertNotIn('F1C-GEN03', [f['penalty_id'] for f in result['findings']])
                self.assertEqual(result['statuses']['F1C-GEN03']['status'], 'not_assessed')

    def test_report_binding_errors_and_inconclusive_verdict_do_not_charge(self):
        for reason in ('Required observations unavailable: Report observation unavailable: binding_unavailable',
                       'Required observations unavailable: Report field amount: mapped_column_absent',
                       'Required observations unavailable: not_declared'):
            with self.subTest(reason=reason):
                rules = self.bu(BU16='inconclusive')
                next(r for r in rules if r['id'] == 'BU16')['reason'] = reason
                result = self.run_with(rules)
                self.assertFalse(any(f['defect_id'] == 'requirement.BU16' for f in result['findings']))
                self.assertFalse(any(f['penalty_id'] == 'F1C-GEN03' for f in result['findings']))

    def test_report_runtime_error_is_still_deduplicated_by_root_cause(self):
        error = ('{ОбщийМодуль.BenchmarkObserver.Модуль(41)}: Ошибка: '
                 '{Отчет.Продажи.МодульОбъекта(64)}: Ошибка выполнения запроса')
        result = self.run_with(self.bu(BU16='fail', BU17='fail'), {'report': {'report_error': error}})
        findings = [(f['penalty_id'], f['defect_id']) for f in result['findings']]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0][0], 'F1C-GEN12')
        self.assertTrue(findings[0][1].startswith('code.'))

    def test_one_code_error_breaking_many_requirements_is_one_defect(self):
        error = ("{ОбщийМодуль.BenchmarkObserver.Модуль(41)}: Error calling context method (Записать): Error running processor - 'ОбработкаПроведения': "
                 "{ОбщийМодуль.УчетСервер.Модуль(64)}: Error calling context method (Выполнить): {(1, 114)}: Wrong parameters\nВЫБРАТЬ ...")
        observations = {case: {'posting_error': error} for case in ('chain', 'own_first', 'average')}
        result = self.run_with(self.bu(BU03='fail', BU08='fail', BU13='fail'), observations)
        self.assertEqual([f['penalty_id'] for f in result['findings']], ['F1C-GEN12'])
        self.assertEqual(result['score']['deductions'], '0.25')
        self.assertEqual(signature(error), 'ОбщийМодуль.УчетСервер.Модуль(64): Error calling context method (Выполнить): Wrong parameters')

    def query_module(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('Запрос = Новый Запрос("ВЫБРАТЬ Т.Нет ИЗ Справочник.Склады КАК Т");\nЗапрос2 = Новый Запрос("ВЫБРАТЬ 1 ИЗ ВТ КАК ВТ");\n'
                        'Текст = "ВЫБРАТЬ 1 ИЗ " + Имя;', encoding='utf-8-sig')

    def test_query_text_rejected_by_the_platform_is_a_code_defect(self):
        self.query_module()
        observation = {'query_texts': {'checked': [{'index': 0, 'error': '{(1, 10)}: Поле не найдено "Т.Нет"\nТ.<<?>>Нет'},
                                                   {'index': 1, 'error': '{(1, 14)}: Таблица не найдена "ВТ"'}]}}
        result = self.run_with(self.bu(), observation)
        self.assertEqual([(f['penalty_id'], f['defect_id'], f['proof_kind']) for f in result['findings']],
                         [('F1C-GEN12', 'code.query.CommonModules/Учет/Ext/Module.bsl:1', 'query_parse')])
        self.assertIn('Поле не найдено "Т.Нет"', result['findings'][0]['reason'])
        self.assertEqual(result['score']['deductions'], '0.25')

    def test_query_error_already_proved_by_a_scenario_is_not_charged_twice(self):
        self.query_module()
        error = ('{ОбщийМодуль.BenchmarkObserver.Модуль(41)}: Ошибка при вызове метода контекста (Записать): '
                 '{ОбщийМодуль.Учет.Модуль(1)}: Ошибка при вызове метода контекста (Выполнить): {(1, 10)}: Поле не найдено "Т.Нет"')
        observations = {case: {'posting_error': error} for case in ('chain', 'own_first')}
        observations['query_texts'] = {'checked': [{'index': 0, 'error': '{(1, 10)}: Поле не найдено "Т.Нет"\nТ.<<?>>Нет'}, {'index': 1, 'error': ''}]}
        result = self.run_with(self.bu(BU03='fail', BU08='fail'), observations)
        self.assertEqual([f['defect_id'][:12] for f in result['findings']], ['code.ОбщийМо'])

    def test_missing_field_in_table_parameter_does_not_create_unproved_penalty(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('Запрос = Новый Запрос("ВЫБРАТЬ Сотрудник ПОМЕСТИТЬ ВТ ИЗ &Периоды КАК Т");', encoding='utf-8')
        observations = {'query_texts': {'checked': [{'index': 0, 'error': 'Поле не найдено "Сотрудник"'}]}}
        result = self.run_with(self.bu(), observations)
        self.assertFalse(any(f['penalty_id'] == 'F1C-GEN12' for f in result['findings']))
        self.assertEqual(result['statuses']['F1C-GEN12']['status'], 'not_assessed')

    def test_runtime_error_still_counts_when_parameter_schema_is_unresolved(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('Запрос = Новый Запрос("ВЫБРАТЬ Нет ПОМЕСТИТЬ ВТ ИЗ &Периоды КАК Т");', encoding='utf-8')
        error = ('{ОбщийМодуль.BenchmarkObserver.Модуль(41)}: Ошибка при вызове метода контекста (Записать): '
                 '{ОбщийМодуль.Учет.Модуль(1)}: Ошибка при вызове метода контекста (Выполнить): {(1, 10)}: Поле не найдено "Нет"')
        observations = {case: {'posting_error': error} for case in ('chain', 'own_first')}
        observations['query_texts'] = {'checked': [{'index': 0, 'error': 'Поле не найдено "Нет"'}]}
        result = self.run_with(self.bu(BU03='fail', BU08='fail'), observations)
        self.assertTrue(any(f['penalty_id'] == 'F1C-GEN12' and f['proof_kind'] == 'runtime_error' for f in result['findings']))
        self.assertEqual(result['statuses']['F1C-GEN12']['status'], 'violation')

    def test_all_query_texts_parsed_is_no_violation_with_its_limits(self):
        self.query_module()
        result = self.run_with(self.bu(), {'query_texts': {'checked': [{'index': 0, 'error': ''}, {'index': 1, 'error': '{(1, 14)}: Таблица не найдена "ВТ"'}]}})
        self.assertEqual(result['statuses']['F1C-GEN12']['status'], 'no_violation_found')
        self.assertIn('1 текстов запросов без ошибок; не проверено: 1 собираемых из частей, 1 со ссылкой', result['statuses']['F1C-GEN12']['reason'])

    def test_posting_that_ignores_a_manual_register_entry_takes_data_not_from_the_register(self):
        result = self.run_with(self.bu(BU02='fail'))
        self.assertIn(('F1C-GEN05', 'requirement.BU02'), [(f['penalty_id'], f['defect_id']) for f in result['findings']])
        self.assertEqual(self.run_with(self.bu())['statuses']['F1C-GEN05']['status'], 'no_violation_found')
        # Cost already wrong without a manual entry: the failure of BU02 does not single out the register.
        self.assertEqual(self.run_with(self.bu(BU02='fail', BU13='fail'))['statuses']['F1C-GEN05']['status'], 'not_assessed')

    def test_form_independence_needs_every_operational_requirement(self):
        ou = [{'id': r['id'], 'verdict': 'pass', 'reason': None} for r in self.requirements if r['section'] == 'OU']
        self.assertEqual(self.run_with(self.bu() + ou)['statuses']['F1C-OU04']['status'], 'no_violation_found')
        ou[0]['verdict'] = 'fail'
        self.assertEqual(self.run_with(self.bu() + ou)['statuses']['F1C-OU04']['status'], 'not_assessed')

    def test_storno_by_hand_without_the_platform_method(self):
        path = self.src / 'Documents/Начисление/Ext/ObjectModule.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('// ПолучитьДополнение() здесь не вызывается\nДвижение.Сторно = Истина;', encoding='utf-8-sig')
        result = self.run_with(self.bu())
        self.assertIn(('F1C-PR16', 'pr.manual_storno'), [(f['penalty_id'], f['defect_id']) for f in result['findings']])
        path.write_text('Дополнение = Движения.Начисления.ПолучитьДополнение();\nДвижение.Сторно = Истина;', encoding='utf-8-sig')
        self.assertEqual(self.run_with(self.bu())['statuses']['F1C-PR16']['status'], 'no_violation_found')

    def chart(self, warehouse_sum, profit_turnover):
        """A ledger with an amount flag per subconto, goods 01.02 by items and warehouses, profit 03 by items."""
        self.binding = dict(self.binding, objects=dict(self.binding['objects'], ledger='AccountingRegister.Учет', accounts='ChartOfAccounts.План',
                                                       warehouses='Catalog.Склады', items='Catalog.Номенклатура'),
                            account_codes={'goods': '01.02', 'profit': '03'}, fields={'ledger': {'amount': 'Сумма'}})
        (self.src / 'AccountingRegisters').mkdir(exist_ok=True)
        (self.src / 'AccountingRegisters/Учет.xml').write_text('<AccountingRegister><Resource uuid="1"><Properties><Name>Сумма</Name>'
                                                               '<ExtDimensionAccountingFlag>ChartOfAccounts.План.ExtDimensionAccountingFlag.Суммовой</ExtDimensionAccountingFlag>'
                                                               '</Properties></Resource><ChartOfAccounts>ChartOfAccounts.План</ChartOfAccounts></AccountingRegister>')
        (self.src / 'ChartsOfAccounts/План/Ext').mkdir(parents=True, exist_ok=True)
        (self.src / 'ChartsOfAccounts/План.xml').write_text('<ChartOfAccounts><ExtDimensionTypes>ChartOfCharacteristicTypes.Виды</ExtDimensionTypes></ChartOfAccounts>')
        kind = lambda name, turnover, on: ('<ExtDimensionType name="ChartOfCharacteristicTypes.Виды.%s"><Turnover>%s</Turnover><AccountingFlags>'
                                           '<Flag ref="ChartOfAccounts.План.ExtDimensionAccountingFlag.Суммовой">%s</Flag></AccountingFlags></ExtDimensionType>' % (name, turnover, on))
        (self.src / 'ChartsOfAccounts/План/Ext/Predefined.xml').write_text(
            '<Item id="1"><Name>Активы</Name><Code>01</Code><ExtDimensionTypes/><ChildItems>'
            '<Item id="2"><Name>Товары</Name><Code>01.02</Code><ExtDimensionTypes>%s%s</ExtDimensionTypes></Item></ChildItems></Item>'
            '<Item id="3"><Name>Прибыль</Name><Code>03</Code><ExtDimensionTypes>%s</ExtDimensionTypes></Item>'
            % (kind('Номенклатура', 'false', 'true'), kind('Склады', 'false', warehouse_sum), kind('Номенклатура', profit_turnover, 'true')))
        (self.src / 'ChartsOfCharacteristicTypes/Виды/Ext').mkdir(parents=True, exist_ok=True)
        (self.src / 'ChartsOfCharacteristicTypes/Виды/Ext/Predefined.xml').write_text(
            '<Item id="a"><Name>Номенклатура</Name><Type><v8:Type>d4p1:CatalogRef.Номенклатура</v8:Type></Type></Item>'
            '<Item id="b"><Name>Склады</Name><Type><v8:Type>d4p1:CatalogRef.Склады</v8:Type></Type></Item>')

    def test_subconto_flags_follow_the_ticket(self):
        self.chart('true', 'false')
        found = {f['penalty_id']: f['defect_id'] for f in self.run_with(self.bu())['findings']}
        self.assertEqual((found.get('F1C-BU07'), found.get('F1C-BU08')), ('bu.subconto_flags', 'bu.profit_balances'))
        self.chart('false', 'true')
        statuses = self.run_with(self.bu())['statuses']
        self.assertEqual((statuses['F1C-BU07']['status'], statuses['F1C-BU08']['status']), ('no_violation_found', 'no_violation_found'))

    def test_query_result_unloaded_only_to_be_walked_once(self):
        path = self.src / 'Catalogs/Склады/Forms/Форма/Ext/Form/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('''Процедура Один()
	Т = Запрос.Выполнить().Выгрузить();
	Для Каждого С Из Т Цикл
		Сообщить(С.Поле);
	КонецЦикла;
КонецПроцедуры
Процедура Поиск()
	Т = Запрос.Выполнить().Выгрузить();
	Строка = Т.Найти(1, "Поле");
КонецПроцедуры
Процедура Повтор()
	Т = Запрос.Выполнить().Выгрузить();
	Для Каждого Д Из Документы Цикл
		Для Каждого С Из Т Цикл
		КонецЦикла;
	КонецЦикла;
КонецПроцедуры
''', encoding='utf-8-sig')
        found = [f['defect_id'] for f in self.run_with(self.bu())['findings'] if f['penalty_id'] == 'F1C-GEN25']
        self.assertEqual(found, ['code.unload.Catalogs/Склады/Forms/Форма/Ext/Form/Module.bsl:2'])

    def duplicates(self, over_posted, split_cost):
        self.binding = dict(self.binding, account_codes={'goods': '01.02', 'customers': '01.04', 'profit': '03'})
        before = [{'debit': '01.02', 'credit': '02.02', 'amount': 260, 'registrar': 'Приход'}]
        sale = [{'debit': '03', 'credit': '01.02', 'amount': split_cost, 'registrar': 'Расход'}, {'debit': '01.04', 'credit': '03', 'amount': 80, 'registrar': 'Расход'}]
        over_after = before + sale if over_posted else before
        return {'dup_split': {'posted': True, 'before': before, 'after': before + sale},
                'dup_over': {'posted': over_posted, 'before': before, 'after': over_after, 'all_before': {}, 'all_after': {}}}

    def test_duplicate_lines_against_their_single_line_twins(self):
        status = lambda obs, **v: self.run_with(self.bu(**v), obs)['statuses']['F1C-GEN19']['status']
        self.assertEqual(status(self.duplicates(False, 52)), 'no_violation_found')
        self.assertEqual(status(self.duplicates(True, 52)), 'violation')        # control by line
        self.assertEqual(status(self.duplicates(False, 26)), 'violation')       # second line lost
        self.assertEqual(status(self.duplicates(True, 52), BU10='fail'), 'not_assessed')  # oversell refused by nobody

    def test_unposting_restores_the_registers(self):
        status = lambda average: self.run_with(self.bu(), {'average': average})['statuses']['F1C-GEN17']['status']
        self.assertEqual(status({'all_before': {'BU_Учет': ['a']}, 'undone_all': {'BU_Учет': ['a']}}), 'no_violation_found')
        self.assertEqual(status({'all_before': {'BU_Учет': ['a']}, 'undone_all': {'BU_Учет': ['a', 'b']}}), 'violation')
        self.assertEqual(status({'undo_error': 'Ошибка при отмене проведения'}), 'violation')
        self.assertEqual(status({'posted': False}), 'not_assessed')

    def test_posting_reading_balances_without_any_managed_lock(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('Запрос = Новый Запрос("ВЫБРАТЬ О.КоличествоОстаток ИЗ РегистрНакопления.Т.Остатки(&М, ) КАК О");', encoding='utf-8-sig')
        self.assertIn(('F1C-GEN29', 'locks.none'), [(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']])
        path.write_text('Блокировка = Новый БлокировкаДанных; Блокировка.Добавить("РегистрНакопления.Т");\nЗапрос = Новый Запрос("ВЫБРАТЬ О.КоличествоОстаток ИЗ РегистрНакопления.Т.Остатки(&М, ) КАК О");', encoding='utf-8-sig')
        self.assertEqual(self.run_with(self.bu())['statuses']['F1C-GEN29']['status'], 'no_violation_found')

    def test_for_update_clause_in_managed_mode(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('Блокировка = Новый БлокировкаДанных;\nЗапрос = Новый Запрос("ВЫБРАТЬ О.КоличествоОстаток ИЗ РегистрНакопления.Т.Остатки(&М, ) КАК О\n'
                        '|ДЛЯ ИЗМЕНЕНИЯ РегистрНакопления.Т.Остатки");', encoding='utf-8-sig')
        self.assertIn(('F1C-GEN29', 'locks.for_update'), [(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']])

    def test_registrar_fields_and_order_by_date_in_queries(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        found = lambda: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']}
        path.write_text('Запрос = Новый Запрос("ВЫБРАТЬ Т.Регистратор.Склад КАК Склад ИЗ РегистрНакопления.Т КАК Т");', encoding='utf-8-sig')
        self.assertIn(('F1C-GEN05', 'code.registrar_fields'), found())
        path.write_text('Запрос = Новый Запрос("ВЫБРАТЬ О.Партия КАК Партия ИЗ РегистрНакопления.П.Остатки(&М, ) КАК О\n|УПОРЯДОЧИТЬ ПО О.Партия.Дата");', encoding='utf-8-sig')
        self.assertIn(('F1C-GEN10', 'code.order_by_date'), found())
        path.write_text('Запрос = Новый Запрос("ВЫБРАТЬ О.Партия КАК Партия ИЗ РегистрНакопления.П.Остатки(&М, ) КАК О\n|УПОРЯДОЧИТЬ ПО О.Партия.МоментВремени");\n'
                        'Запрос2 = Новый Запрос("ВЫБРАТЬ Т.Регистратор.Ссылка КАК Р ИЗ РегистрНакопления.Т КАК Т");', encoding='utf-8-sig')
        self.assertFalse({p for p, d in found() if d in ('code.registrar_fields', 'code.order_by_date')})

    def test_accounting_flags_not_linked_to_resources(self):
        self.chart('false', 'true')
        flags = ('<ExtDimensionAccountingFlag uuid="9"><Properties><Name>Суммовой</Name></Properties></ExtDimensionAccountingFlag>'
                 '<ExtDimensionAccountingFlag uuid="8"><Properties><Name>Валютный</Name></Properties></ExtDimensionAccountingFlag>')
        chart = self.src / 'ChartsOfAccounts/План.xml'
        chart.write_text(chart.read_text().replace('</ChartOfAccounts>', flags + '</ChartOfAccounts>'))
        statuses = self.run_with(self.bu())['statuses']
        self.assertEqual(statuses['F1C-BU07']['status'], 'violation')
        self.assertIn('Валютный', statuses['F1C-BU07']['reason'])
        ledger = self.src / 'AccountingRegisters/Учет.xml'
        ledger.write_text(ledger.read_text().replace('</ChartOfAccounts>', '</ChartOfAccounts><Resource uuid="2"><Properties><Name>Количество</Name><Balance>false</Balance>'
                                                     '<AccountingFlag>ChartOfAccounts.План.AccountingFlag.Количественный</AccountingFlag></Properties></Resource>'))
        chart.write_text(chart.read_text().replace('</ChartOfAccounts>', '<AccountingFlag uuid="7"><Properties><Name>Количественный</Name></Properties></AccountingFlag>'
                                                   '<AccountingFlag uuid="6"><Properties><Name>Валютный</Name></Properties></AccountingFlag></ChartOfAccounts>'))
        statuses = self.run_with(self.bu())['statuses']
        self.assertEqual(statuses['F1C-BU06']['status'], 'violation')
        self.assertIn('признак учёта Валютный', statuses['F1C-BU06']['reason'])

    def test_division_by_zero_in_the_zero_divisor_scenario(self):
        found = lambda obs: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu(), observations=obs)['findings']}
        self.assertIn(('F1C-GEN12', 'code.division_by_zero'), found({'pr_zero': {'posted': {'no_base': False}, 'errors': {'no_base': '{Документ.Н.МодульОбъекта(76)}: Division by zero'}}}))
        self.assertNotIn(('F1C-GEN12', 'code.division_by_zero'), found({'pr_zero': {'posted': {'no_base': True, 'no_schedule': True}, 'errors': {}}}))

    def test_lock_for_change_without_totals_splitting(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('Движения.Партии.БлокироватьДляИзменения = Истина;\nБлокировка = Новый БлокировкаДанных;', encoding='utf-8-sig')
        (self.src / 'AccumulationRegisters').mkdir()
        register = self.src / 'AccumulationRegisters/Партии.xml'
        found = lambda: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']}
        register.write_text('<AccumulationRegister><EnableTotalsSplitting>false</EnableTotalsSplitting></AccumulationRegister>')
        self.assertIn(('F1C-GEN29', 'locks.lock_for_change_no_splitting'), found())
        register.write_text('<AccumulationRegister><EnableTotalsSplitting>true</EnableTotalsSplitting></AccumulationRegister>')
        self.assertNotIn(('F1C-GEN29', 'locks.lock_for_change_no_splitting'), found())

    def test_posted_document_writing_modified_sets(self):
        doc = self.src / 'Documents/Сборка.xml'
        found = lambda: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']}
        doc.write_text('<Document><Posting>Allow</Posting><RegisterRecords><xr:Item xsi:type="xr:MDObjectRef">AccumulationRegister.Т</xr:Item></RegisterRecords>'
                       '<RegisterRecordsWritingOnPost>WriteModified</RegisterRecordsWritingOnPost></Document>')
        self.assertIn(('F1C-GEN28', 'posting.write_modified'), found())
        doc.write_text(doc.read_text().replace('WriteModified', 'WriteSelected'))
        self.assertNotIn(('F1C-GEN28', 'posting.write_modified'), found())

    def test_removed_starter_objects(self):
        found = lambda: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']}
        self.assertNotIn(('F1C-GEN01', 'starter.objects_removed'), found())  # not built on the issued starter
        (self.src / 'Configuration.xml').write_text('<Configuration uuid="%s"><DataLockControlMode>Managed</DataLockControlMode></Configuration>' % self.starter['configuration_uuid'])
        for key, uid in self.starter['objects_uuid'].items():
            group, name = key.split('/')
            (self.src / group).mkdir(exist_ok=True)
            (self.src / group / (name + '.xml')).write_text('<X uuid="%s"/>' % uid)
        self.assertNotIn(('F1C-GEN01', 'starter.objects_removed'), found())
        (self.src / 'Enums/УчетнаяПолитика.xml').unlink()
        self.assertIn(('F1C-GEN01', 'starter.objects_removed'), found())

    def test_balances_read_without_a_lock_on_that_register(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        query = ' Запрос = Новый Запрос("ВЫБРАТЬ О.КоличествоОстаток ИЗ РегистрНакопления.Т.Остатки(&М, ) КАК О"); Запрос.Выполнить();\n'
        found = lambda: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']}
        helper = 'Процедура Заблокировать(Имя) Экспорт\n Б = Новый БлокировкаДанных; Б.Добавить(Имя); Б.Заблокировать();\nКонецПроцедуры\n'
        cases = {
            # read before any write, another register locked: no lock covers Т (#std460)
            'Процедура П()\n Б = Новый БлокировкаДанных; Б.Добавить("РегистрНакопления.Другой"); Б.Заблокировать();\n' + query + 'КонецПроцедуры\n': 'locks.unlocked_reads',
            # lock taken after the read in the same method
            'Процедура П()\n Б = Новый БлокировкаДанных;\n' + query + ' Б.Добавить("РегистрНакопления.Т"); Б.Заблокировать();\nКонецПроцедуры\n': 'locks.after_read',
            # lock through a helper before the read
            helper + 'Процедура П()\n Заблокировать("РегистрНакопления.Т");\n' + query + 'КонецПроцедуры\n': None,
            # new method: movements written first, then the balances are checked (#std661)
            'Процедура П()\n Б = Новый БлокировкаДанных;\n Движения.Т.Записать();\n' + query + 'КонецПроцедуры\n': None,
        }
        for text, expected in cases.items():
            with self.subTest(expected):
                path.write_text(text, encoding='utf-8-sig')
                got = {d for p, d in found() if p == 'F1C-GEN29'}
                self.assertEqual(got, {expected} if expected else set())

    def test_shared_lock_on_a_register_the_solution_writes(self):
        (self.src / 'Documents/Расход.xml').write_text('<Document><RegisterRecords><xr:Item xsi:type="xr:MDObjectRef">AccumulationRegister.Т</xr:Item></RegisterRecords></Document>')
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        lock = 'Процедура П()\n Б = Новый БлокировкаДанных; Э = Б.Добавить("РегистрНакопления.Т"); Э.Режим = РежимБлокировкиДанных.%s; Б.Заблокировать();\nКонецПроцедуры\n'
        found = lambda: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']}
        path.write_text(lock % 'Разделяемый', encoding='utf-8-sig')
        self.assertIn(('F1C-GEN29', 'locks.shared_on_written'), found())
        path.write_text(lock % 'Исключительный', encoding='utf-8-sig')
        self.assertNotIn(('F1C-GEN29', 'locks.shared_on_written'), found())

    def test_base_read_before_the_records_are_written(self):
        (self.src / 'CalculationRegisters').mkdir()
        (self.src / 'CalculationRegisters/Начисления.xml').write_text('<CalculationRegister/>')
        module = self.src / 'Documents/Начисление/Ext/ObjectModule.bsl'
        module.parent.mkdir(parents=True)
        base = 'З = Новый Запрос("ВЫБРАТЬ Б.РезультатБаза ИЗ РегистрРасчета.Начисления.БазаНачисления(&И, &И, , Регистратор = &Р) КАК Б");\n'
        found = lambda: {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']}
        module.write_text('Процедура ОбработкаПроведения(Отказ)\n' + base + ' Движения.Начисления.Записать();\nКонецПроцедуры\n', encoding='utf-8-sig')
        self.assertIn(('F1C-PR13', 'pr.base_before_write'), found())
        module.write_text('Процедура ОбработкаПроведения(Отказ)\n Движения.Начисления.Записать();\n' + base + 'КонецПроцедуры\n', encoding='utf-8-sig')
        self.assertNotIn(('F1C-PR13', 'pr.base_before_write'), found())

    def test_main_table_joined_with_its_schedule_data(self):
        path = self.src / 'CommonModules/Расчет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        path.write_text('З = Новый Запрос("ВЫБРАТЬ Н.НомерСтроки ИЗ РегистрРасчета.Начисления КАК Н ЛЕВОЕ СОЕДИНЕНИЕ '
                        'РегистрРасчета.Начисления.ДанныеГрафика(Регистратор = &Р) КАК Д ПО Н.НомерСтроки = Д.НомерСтроки");', encoding='utf-8-sig')
        self.assertIn(('F1C-GEN23', 'query.schedule_joined_to_main'), {(f['penalty_id'], f['defect_id']) for f in self.run_with(self.bu())['findings']})

    def test_hidden_and_base_reads_in_loops(self):
        path = self.src / 'CommonModules/Учет/Ext/Module.bsl'
        path.parent.mkdir(parents=True)
        status = lambda: self.run_with(self.bu())['statuses']['F1C-GEN20']['status']
        cases = {
            'Пока Выборка.Следующий() Цикл\n Имя = Выборка.Товар.Наименование;\nКонецЦикла;': 'not_assessed',  # no source/type evidence in this fixture
            'Для Каждого Запись Из Набор Цикл\n База = РегистрыРасчета.Начисления.ПолучитьБазу(Отбор, Ресурсы, Измерения);\nКонецЦикла;': 'violation',
            'Пока Выборка.Следующий() Цикл\n Имя = Выборка.Наименование;\n Набор.Отбор.Регистратор.Установить(Выборка.Ссылка);\nКонецЦикла;': 'no_violation_found',
            'Для Каждого Пара Из Наборы Цикл\n Пара.Значение.Записать();\n Сумма = Пара.Значение.Количество;\nКонецЦикла;': 'no_violation_found',
            'Имя = Выборка.Товар.Наименование;': 'no_violation_found',
            'Пока Выборка.Следующий() Цикл\n Сообщить("Не хватает " + Выборка.Ссылка);\nКонецЦикла;': 'violation',
            'Пока Выборка.Следующий() Цикл\n Сообщить("Не хватает " + Выборка.Ссылка); Возврат;\nКонецЦикла;': 'no_violation_found',
            'Пока Выборка.Следующий() Цикл\n Сообщить("Не хватает " + Выборка.Количество);\nКонецЦикла;': 'no_violation_found',
        }
        for text, expected in cases.items():
            with self.subTest(text):
                path.write_text('Процедура П()\n' + text + '\nКонецПроцедуры\n', encoding='utf-8-sig')
                self.assertEqual(status(), expected)

    def test_actual_action_period_rewritten_after_calculation(self):
        self.binding = dict(self.binding, pr={'results': [{'register': 'CalculationRegister.Начисления'}]})
        (self.src / 'CalculationRegisters').mkdir()
        (self.src / 'CalculationRegisters/Начисления.xml').write_text('<CalculationRegister><ActionPeriod>true</ActionPeriod><Schedule>InformationRegister.Графики</Schedule>'
                                                                     '<ChartOfCalculationTypes>ChartOfCalculationTypes.Виды</ChartOfCalculationTypes></CalculationRegister>')
        document = self.src / 'Documents/Начисление/Ext/ObjectModule.bsl'
        document.parent.mkdir(parents=True)
        document.write_text('Процедура ОбработкаПроведения(Отказ)\n Движения.Начисления.Записать();\n Расчет.Рассчитать(Движения.Начисления);\nКонецПроцедуры\n', encoding='utf-8-sig')
        module = self.src / 'CommonModules/Расчет/Ext/Module.bsl'
        module.parent.mkdir(parents=True)
        calc = 'Процедура Рассчитать(Набор) Экспорт\n Для Каждого З Из Набор Цикл З.Результат = 1; КонецЦикла;\n Набор.Записать(%s);\nКонецПроцедуры\n'
        status = lambda: self.run_with(self.bu())['statuses']['F1C-PR14']['status']
        module.write_text(calc % '', encoding='utf-8-sig')
        self.assertEqual(status(), 'violation')
        for args in (', Истина', ', , Ложь'):
            module.write_text(calc % args, encoding='utf-8-sig')
            self.assertEqual(status(), 'no_violation_found', args)

    def test_subconto_flags_not_set_up_is_a_violation(self):
        self.chart('false', 'true')
        ledger = self.src / 'AccountingRegisters/Учет.xml'
        ledger.write_text(ledger.read_text().replace('<ExtDimensionAccountingFlag>ChartOfAccounts.План.ExtDimensionAccountingFlag.Суммовой</ExtDimensionAccountingFlag>', ''))
        self.assertEqual(self.run_with(self.bu())['statuses']['F1C-BU07']['status'], 'violation')

    def test_whole_section_failed_is_its_section_penalty_and_core_failure(self):
        result = self.run_with(self.bu('fail'))
        self.assertEqual([f['penalty_id'] for f in result['findings']], ['F1C-BU01'])
        self.assertEqual(result['score']['attestation'], 'not_passed_required_section_absent')

    def test_static_signs(self):
        self.config('Automatic')
        self.accounts(['Активы'])
        (self.src / 'Documents' / 'ВводОстатков.xml').write_text('<Document><Synonym><v8:content>Ввод остатков</v8:content></Synonym></Document>')
        (self.src / 'Documents' / 'Сборка.xml').write_text('<Document/>')
        result = self.run_with(self.bu())
        found = {f['penalty_id']: f['defect_id'] for f in result['findings']}
        self.assertEqual(found, {'F1C-GEN29': 'locks.mode', 'F1C-BU11': 'bu.accounts_removed', 'F1C-GEN33': 'document.ВводОстатков'})

    def test_used_register_left_automatic_is_a_lock_violation_only_in_mixed_mode(self):
        self.config('AutomaticAndManaged')
        (self.src / 'AccountingRegisters').mkdir()
        (self.src / 'AccountingRegisters' / 'Учет.xml').write_text('<AccountingRegister><DataLockControlMode>Automatic</DataLockControlMode></AccountingRegister>')
        self.binding['objects']['ledger'] = 'AccountingRegister.Учет'
        result = self.run_with(self.bu())
        self.assertEqual([(f['penalty_id'], f['reason']) for f in result['findings']],
                         [('F1C-GEN29', 'автоматический режим блокировок: AccountingRegister.Учет')])
        self.config('Managed')  # the platform ignores the mode of single objects in the managed mode
        self.assertEqual(self.run_with(self.bu())['findings'], [])

    def module(self, name, text):
        path = self.src / 'CommonModules' / name / 'Ext' / 'Module.bsl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_code_signs(self):
        self.binding['pr'] = {'objects': {'schedules': 'InformationRegister.Графики'}, 'results': [{'register': 'CalculationRegister.Начисления'}]}
        self.module('Учет', '''Процедура Провести(Набор)
 Для Каждого Стр Из Набор Цикл
  Запрос = Новый Запрос("ВЫБРАТЬ Т.Часы ИЗ РегистрСведений.Графики КАК Т"); Т = Запрос.Выполнить();
 КонецЦикла;
 Для Этап = 1 По 2 Цикл Запрос.Выполнить(); КонецЦикла;
 З = Новый Запрос("ВЫБРАТЬ СУММА(Т.Результат) ИЗ РегистрРасчета.Начисления КАК Т");
 О = Новый Запрос("ВЫБРАТЬ Т.КолОстаток ИЗ РегистрНакопления.Остатки.Остатки(, ) КАК Т");
КонецПроцедуры
''')
        result = self.run_with(self.bu())
        found = {f['penalty_id']: f for f in result['findings']}
        # PR05 too: the synthetic calculation register has no metadata, hence no schedule link.
        # The fixture reads balances in posting and locks nothing: also the managed-lock sign.
        self.assertEqual(set(found), {'F1C-GEN20', 'F1C-GEN21', 'F1C-PR06', 'F1C-PR08', 'F1C-PR05', 'F1C-GEN29'})
        self.assertEqual([e['line'] for e in found['F1C-GEN20']['evidence']], [3])  # the fixed two-stage loop is not a data loop
        self.module('Учет', 'Функция Б() Возврат РегистрыРасчета.Начисления.ПолучитьБазу(); КонецФункции\n' + 'З = Новый Запрос("ВЫБРАТЬ * ИЗ РегистрРасчета.Начисления КАК Т");')
        self.assertNotIn('F1C-PR08', {f['penalty_id'] for f in self.run_with(self.bu())['findings']})

    def test_ordinary_forms_of_starter_objects_are_not_the_solutions(self):
        (self.src / 'Configuration.xml').write_text('<Configuration><DataLockControlMode>Managed</DataLockControlMode><DefaultRunMode>ManagedApplication</DefaultRunMode></Configuration>')
        starter_form = self.src / 'DataProcessors/КонсольЗапросов/Forms/Форма.xml'
        starter_form.parent.mkdir(parents=True)
        starter_form.write_text('<Form><FormType>Ordinary</FormType></Form>')
        self.assertEqual(self.run_with(self.bu())['statuses']['F1C-GEN27']['status'], 'no_violation_found')
        own = self.src / 'Documents/Операция/Forms/Форма.xml'
        own.parent.mkdir(parents=True)
        own.write_text('<Form><FormType>Ordinary</FormType></Form>')
        self.assertEqual([f['penalty_id'] for f in self.run_with(self.bu())['findings']], ['F1C-GEN27'])

    def test_failed_requirement_proves_specific_items_but_charges_the_smallest(self):
        result = self.run_with(self.bu(BU14='fail'))
        self.assertEqual(result['statuses']['F1C-BU04']['status'], 'violation')
        self.assertEqual(result['score']['deductions'], '0.5')  # М4.1 (0.5) beats М6.4 (2.0) for the same defect
        self.assertEqual(result['statuses']['F1C-GEN09']['status'], 'no_violation_found')  # BU10 passed

    def test_ledger_quantity_without_accounting_flag(self):
        (self.src / 'AccountingRegisters').mkdir()
        resource = lambda name, balance, flag: (f'<Resource uuid="x"><Properties><Name>{name}</Name><Balance>{balance}</Balance>'
                                                f'<AccountingFlag>{flag}</AccountingFlag></Properties></Resource>')
        (self.src / 'AccountingRegisters' / 'Учет.xml').write_text('<AccountingRegister><ChartOfAccounts>ChartOfAccounts.Управленческий</ChartOfAccounts>'
            + resource('Сумма', 'true', '') + resource('Количество', 'false', '') + '</AccountingRegister>')
        self.binding['objects']['ledger'] = 'AccountingRegister.Учет'
        result = self.run_with(self.bu())
        self.assertEqual(result['statuses']['F1C-BU06']['status'], 'violation')
        (self.src / 'AccountingRegisters' / 'Учет.xml').write_text('<AccountingRegister><ChartOfAccounts>ChartOfAccounts.Управленческий</ChartOfAccounts>'
            + resource('Сумма', 'true', '') + resource('Количество', 'false', 'ChartOfAccounts.Управленческий.AccountingFlag.Количественный') + '</AccountingRegister>')
        self.assertEqual(self.run_with(self.bu())['statuses']['F1C-BU06']['status'], 'no_violation_found')

    def test_item_and_warehouse_as_ledger_dimensions_are_extra_analytics(self):
        (self.src / 'AccountingRegisters').mkdir()
        dim = lambda name, typ: f'<Dimension uuid="x"><Properties><Name>{name}</Name><Type><v8:Type>cfg:CatalogRef.{typ}</v8:Type></Type></Properties></Dimension>'
        (self.src / 'AccountingRegisters' / 'Учет.xml').write_text('<AccountingRegister>' + dim('Номенклатура', 'Номенклатура') + dim('Организация', 'Организации') + '</AccountingRegister>')
        self.binding['objects'].update(ledger='AccountingRegister.Учет', items='Catalog.Номенклатура', warehouses='Catalog.Склады')
        result = self.run_with(self.bu())
        self.assertEqual(result['statuses']['F1C-BU05']['reason'], 'аналитика счетов вынесена в измерения регистра бухгалтерии и есть у всех счетов: Номенклатура (Номенклатура)')

    def test_no_reports_at_all_is_a_missing_report_per_role(self):
        (self.src / 'Reports' / 'R.xml').unlink()
        result = self.run_with(self.bu())
        self.assertEqual(sorted(f['defect_id'] for f in result['findings']),
                         ['report.bu_sales', 'report.ou_sales', 'report.ou_statement', 'report.pr_bonus'])

    def test_missing_demo_data(self):
        result = self.run_with(self.bu(), gates={'demo_data': {'status': 'not_declared'}})
        self.assertEqual([f['penalty_id'] for f in result['findings']], ['F1C-GEN32'])

    def test_every_applicable_rule_has_a_status(self):
        result = self.run_with(self.bu())
        applicable = {i['id'] for i in self.catalogue['items'] if i['applicability'] in ('applicable', 'conditional')}
        self.assertLessEqual(applicable, set(result['statuses']))


if __name__ == '__main__':
    unittest.main()
