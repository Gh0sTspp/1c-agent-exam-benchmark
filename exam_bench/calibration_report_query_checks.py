"""Live calibration of adversarial report observations on a 1C platform.

This creates disposable control configurations and deliberately broken reports.
It does not read or alter published benchmark runs, and does not assign penalties.
"""
from pathlib import Path

from . import calibration_ou, grader, ou, report_query_checks
from .calibration import generate
from .common import write_json


def _turnovers_only(query):
    query = query.replace('.ОстаткиИОбороты(&НачалоПериода, &КонецПериода, , , Department = &Подразделение)',
                          '.Обороты(&НачалоПериода, &КонецПериода, , Department = &Подразделение)')
    for resource in ('Cost', 'Qty'):
        query = query.replace(f'СУММА(Т.{resource}НачальныйОстаток)', '0')
        query = query.replace(f'СУММА(Т.{resource}КонечныйОстаток)',
                              f'СУММА(Т.{resource}Приход) - СУММА(Т.{resource}Расход)')
    return query


JOIN_MULTIPLY = '''ВЫБРАТЬ Т.Item КАК Номенклатура,
 СУММА(Т.Qty) КАК Количество, СУММА(Т.Cost) КАК Себестоимость,
 СУММА(С.Сумма) КАК Продажа, СУММА(С.Сумма) - СУММА(Т.Cost) КАК Прибыль
ИЗ РегистрНакопления.@BATCHES@ КАК Т
 ВНУТРЕННЕЕ СОЕДИНЕНИЕ Документ.@SALE@.СписокНоменклатуры КАК С ПО Т.Регистратор = С.Ссылка
ГДЕ Т.ВидДвижения = ЗНАЧЕНИЕ(ВидДвиженияНакопления.Расход)
 И Т.Регистратор ССЫЛКА Документ.@SALE@
 И Т.Период МЕЖДУ &НачалоПериода И &КонецПериода
 И С.@DEPARTMENT@ <> ЗНАЧЕНИЕ(Справочник.Подразделения.ПустаяСсылка)
СГРУППИРОВАТЬ ПО Т.Item'''


def calibrate(starter_source, starter_dt, binary, evidence):
    """Return actual and expected results; caller must inspect ``passed``.

    ``evidence`` must be new. Four controls/mutants are run for each of the
    function and DCS architectures. A platform or fixture error is never a
    successful negative control.
    """
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=False)
    original_statement, original_sales = calibration_ou.STATEMENT_QUERY, calibration_ou.SALES_QUERY
    saved = {key: ou.CASES.get(key) for key in report_query_checks.CASES}
    specs = (
        ('balance_control', 'report_balance_contrast', 'pass'),
        ('turnover_only', 'report_balance_contrast', 'fail'),
        ('inner_join', 'report_balance_contrast', 'fail'),
        ('sales_control', 'report_sales_cardinality', 'pass'),
        ('join_multiply', 'report_sales_cardinality', 'fail'),
    )
    results = []
    try:
        ou.CASES.update(report_query_checks.CASES)
        for variant in ('one', 'two'):
            for name, case, expected in specs:
                calibration_ou.STATEMENT_QUERY = original_statement
                calibration_ou.SALES_QUERY = original_sales
                if name == 'turnover_only':
                    calibration_ou.STATEMENT_QUERY = _turnovers_only(original_statement)
                elif name == 'inner_join':
                    calibration_ou.STATEMENT_QUERY = original_statement.replace('ЛЕВОЕ СОЕДИНЕНИЕ', 'ВНУТРЕННЕЕ СОЕДИНЕНИЕ')
                elif name == 'join_multiply':
                    calibration_ou.SALES_QUERY = JOIN_MULTIPLY
                case_dir = evidence / (variant + '_' + name)
                case_dir.mkdir()
                binding = generate(starter_source, case_dir / 'source', variant)
                grade = grader.grade(case_dir / 'source', binding, starter_dt, binary, case_dir / 'grade', [case])
                verdict = report_query_checks.evaluate(case, grade['observations'], binding)
                results.append({'variant': variant, 'control': name, 'expected': expected,
                                'actual': verdict, 'platform_errors': grade['errors'],
                                'passed': verdict['verdict'] == expected and not grade['errors']})
    finally:
        calibration_ou.STATEMENT_QUERY, calibration_ou.SALES_QUERY = original_statement, original_sales
        for key, old in saved.items():
            if old is None:
                ou.CASES.pop(key, None)
            else:
                ou.CASES[key] = old
    summary = {'passed': bool(results) and all(r['passed'] for r in results), 'results': results}
    write_json(evidence / 'summary.json', summary)
    return summary
