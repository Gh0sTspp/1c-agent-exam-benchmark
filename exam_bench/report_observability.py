"""Evidence about report output, separate from conclusions about the solution.

The declared binding is an adapter maintained by the runner.  An absent or
incorrect mapping therefore cannot by itself establish an examination error.
In particular, JSON null in a row does not tell us whether the underlying
column was absent or contained NULL: collect the collection's columns too.
"""

from .grader import report_code


def report_code_with_schema(report, name='ReportRows', department=False):
    """Generate the ordinary report adapter with an optional schema receiver.

    Pass a 1C Structure as the final argument to receive ``columns``.  Existing
    callers may omit it.  Collection types, report execution and row flattening
    remain exactly the same as in the regular adapter.
    """
    code = report_code(report, name, department)
    args = 'Начало, Конец' + (', Подразделение' if department else '')
    old_header = f'Функция {name}({args})\n'
    new_header = f'Функция {name}({args}, СхемаРезультата = Неопределено)\n'
    marker = ' Массив = Новый Массив;\n Если ТипЗнч(Коллекция)'
    if code.count(old_header) != 1 or code.count(marker) != 1:
        raise ValueError('Report adapter changed: cannot instrument column collection safely')
    capture = ''' Если СхемаРезультата <> Неопределено Тогда
  ИменаКолонок = Новый Массив;
  Для Каждого Колонка Из Коллекция.Колонки Цикл ИменаКолонок.Добавить(Колонка.Имя); КонецЦикла;
  СхемаРезультата.Вставить("columns", ИменаКолонок);
 КонецЕсли;
'''
    return code.replace(old_header, new_header, 1).replace(marker, capture + marker, 1)


def inspect_report(fields, required_fields, rows=None, schema=None, error=None):
    """Describe report evidence without assigning penalties.

    ``fields`` maps semantic roles to actual output names. ``schema`` is the
    optional captured structure and ``rows`` are the normalized adapter rows.
    Missing/inconsistent observations, missing binding, and a missing mapped
    column are deliberately inconclusive about the solution itself.
    """
    if error:
        return {'status': 'execution_error', 'fields': {}}
    if fields is None:
        return {'status': 'binding_unavailable', 'fields': {}}
    if not isinstance(fields, dict):
        raise TypeError('fields must be a mapping or None')
    if rows is None:
        return {'status': 'observation_unavailable', 'fields': {}}
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return {'status': 'invalid_observation', 'fields': {}}

    columns = schema.get('columns') if isinstance(schema, dict) else None
    known_columns = isinstance(columns, list) and all(isinstance(c, str) for c in columns)
    folded = {c.casefold() for c in columns} if known_columns else set()
    result = {}
    for role in required_fields:
        mapped = fields.get(role)
        if not isinstance(mapped, str) or not mapped:
            result[role] = {'status': 'mapping_unavailable'}
        elif not known_columns:
            result[role] = {'status': 'schema_unavailable', 'column': mapped}
        elif mapped.casefold() not in folded:
            result[role] = {'status': 'mapped_column_absent', 'column': mapped}
        elif any(role not in row for row in rows):
            result[role] = {'status': 'row_data_unavailable', 'column': mapped}
        else:
            # Preserve values, including 0, empty string and null.  Group and
            # leaf rows are not aggregated: the output may contain both.
            result[role] = {'status': 'observed', 'column': mapped,
                            'values': [row[role] for row in rows]}
    return {'status': 'observed', 'fields': result}


def require_report_fields(fields, required_fields, rows, schema=None, error=None):
    """Reject insufficient evidence, including errors in the report adapter.

    Old snapshots lack a schema: a non-null normalized value proves its mapped
    column was readable. If every value is null, the old adapter cannot tell
    NULL from a missing column; the result must remain inconclusive.
    """
    evidence = inspect_report(fields, required_fields, rows, schema, error)
    if evidence['status'] != 'observed':
        raise ValueError('Report observation unavailable: ' + evidence['status'])
    for role, field in evidence['fields'].items():
        status = field['status']
        if status == 'schema_unavailable' and rows and all(role in row for row in rows):
            if any(row[role] is not None for row in rows):
                continue
        if status != 'observed':
            raise ValueError('Report field %s: %s' % (role, status))
