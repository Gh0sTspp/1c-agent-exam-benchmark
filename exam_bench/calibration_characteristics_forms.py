"""Live controls for dynamic form fields typed from characteristic metadata."""
from pathlib import Path
import xml.etree.ElementTree as E

from .calibration import generate
from .calibration_characteristics import CHART, M, V, _load, _save, configure
from .common import tree_manifest, write_json
from .grader import grade


def configure_form(src, variant):
    """Mirror the ticket's TypeSet storage and metadata-typed dynamic fields."""
    src = Path(src)
    configure(src, 'typeset_no_owner')
    module = src / 'Catalogs/Контрагенты/Forms/Форма/Ext/Form/Module.bsl'
    code = module.read_text(encoding='utf-8-sig')
    old = 'Новый ОписаниеТипов("Строка", , Новый КвалификаторыСтроки(50))'
    if code.count(old) != 1:
        raise ValueError('Dynamic form control has missing or ambiguous field type')
    module.write_text(code.replace(old, 'С.Свойство.ТипЗначения', 1), encoding='utf-8')

    catalog_path = src / 'Catalogs/Контрагенты.xml'
    catalog, opening = _load(catalog_path)
    tables = catalog[0].find(M + 'ChildObjects').findall(M + 'TabularSection')
    table = next(t for t in tables if t.find(M + 'Properties/' + M + 'Name').text == 'Сведения')
    attrs = table.find(M + 'ChildObjects').findall(M + 'Attribute')
    value = next(a for a in attrs if a.find(M + 'Properties/' + M + 'Name').text == 'Значение')
    typ = value.find(M + 'Properties/' + M + 'Type')
    typ.clear()
    E.SubElement(typ, V + 'TypeSet').text = 'cfg:Characteristic.' + CHART
    _save(catalog_path, catalog, opening)

    if variant not in ('positive', 'values_not_saved', 'reference_only', 'short_string'):
        raise ValueError('Unknown dynamic-form control')
    if variant in ('reference_only', 'short_string'):
        chart_path = src / 'ChartsOfCharacteristicTypes' / (CHART + '.xml')
        chart, opening = _load(chart_path)
        types = chart[0].find(M + 'Properties/' + M + 'Type')
        if variant == 'reference_only':
            for t in list(types):
                if (t.tag == V + 'Type' and t.text == 'xs:string') or t.tag == V + 'StringQualifiers':
                    types.remove(t)
        else:
            length = types.find(V + 'StringQualifiers/' + V + 'Length')
            if length is None:
                raise ValueError('Missing string length in chart control')
            length.text = '2'
        _save(chart_path, chart, opening)


def run(starter_source, starter_dt, binary, root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    controls = []
    for variant in ('positive', 'values_not_saved', 'reference_only', 'short_string'):
        folder = root / variant
        folder.mkdir()
        src = folder / 'src'
        mutation = 'values_not_saved' if variant == 'values_not_saved' else None
        binding = generate(starter_source, src, 'one', mutation)
        configure_form(src, variant)
        before = tree_manifest(src)
        result = grade(src, binding, starter_dt, binary, folder / 'grade', ['forms'])
        verdicts = {r['id']: r['verdict'] for r in result['rules'] if r['id'] in ('F01', 'F02', 'F03', 'F04', 'F05')}
        observation = result['observations'].get('forms', {})
        saved = observation.get('forms', {}).get('saved', {})
        stored = sorted((r.get('kind'), r.get('value')) for r in saved.get('stored', []))
        typed = sorted(saved.get('typed', []))
        fixture_error = observation.get('fixture_error')
        if variant in ('reference_only', 'short_string'):
            passed = (not result['errors']
                      and fixture_error == 'Контрольные строки USD и 15 не поддерживаются типом характеристики или поля хранения'
                      and verdicts.get('F04') == 'inconclusive' and verdicts.get('F05') == 'inconclusive')
        else:
            expected = [('BENCH_Валюта', 'USD'), ('BENCH_Срок', '15')]
            passed = (not result['errors'] and not observation.get('errors') and not fixture_error
                      and verdicts.get('F04') == 'pass' and typed == ['C1', 'C2']
                      and saved.get('written') is True and 'error' not in saved
                      and (not stored if mutation else stored == expected)
                      and verdicts.get('F05') == ('fail' if mutation else 'pass'))
        passed = bool(passed and tree_manifest(src) == before)
        controls.append({'case': variant, 'passed': passed, 'verdicts': verdicts,
                         'typed': typed, 'written': saved.get('written'), 'stored': stored,
                         'fixture_error': fixture_error, 'errors': result['errors']})
    summary = {'passed': all(c['passed'] for c in controls), 'controls': controls}
    write_json(root / 'summary.json', summary)
    return summary
