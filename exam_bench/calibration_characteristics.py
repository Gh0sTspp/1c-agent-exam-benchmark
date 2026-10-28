"""Calibrate the characteristic-value fixture against actual 1C metadata variants."""
import re
import uuid
import xml.etree.ElementTree as E
from pathlib import Path

from .calibration import generate
from .common import tree_manifest, write_json
from .grader import grade

M = '{http://v8.1c.ru/8.3/MDClasses}'
V = '{http://v8.1c.ru/8.1/data/core}'
X = '{http://v8.1c.ru/8.3/xcf/readable}'
I = '{http://www.w3.org/2001/XMLSchema-instance}'
CHART = 'СвойстваОбъектов'
CATALOG = 'BenchCharacteristicValues'


def _load(path):
    for _, namespace in E.iterparse(path, events=['start-ns']):
        E.register_namespace(*namespace)
    text = path.read_text(encoding='utf-8-sig')
    return E.fromstring(text), re.search(r'<MetaDataObject\b[^>]*>', text).group()


def _save(path, root, opening):
    text = E.tostring(root, encoding='unicode')
    text = re.sub(r'<MetaDataObject\b[^>]*>', lambda _: opening, text, count=1)
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + text, encoding='utf-8')


def configure(src, variant):
    """Give the generated control a real extra-value catalog and selected value type.

    The typeset variant mirrors #61: the register resource uses the chart's
    allowed types, and the extra catalog itself has no owner.
    """
    if variant == 'plain_string':
        return
    if variant not in ('typeset_no_owner', 'reference_owner', 'reference_no_owner', 'unsupported'):
        raise ValueError('Unknown characteristics control')
    src = Path(src)
    config = src / 'Configuration.xml'
    config_text = config.read_text(encoding='utf-8-sig')
    if config_text.count('</ChildObjects>') != 1:
        raise ValueError('Ambiguous configuration children')
    config.write_text(config_text.replace('</ChildObjects>', '<Catalog>' + CATALOG + '</Catalog></ChildObjects>', 1), encoding='utf-8')

    template = (src / 'Catalogs/Валюты.xml').read_text(encoding='utf-8-sig').replace('Валюты', CATALOG)
    template = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', lambda _: str(uuid.uuid4()), template)
    catalog_path = src / 'Catalogs' / (CATALOG + '.xml')
    catalog_path.write_text(template, encoding='utf-8')
    catalog, opening = _load(catalog_path)
    owners = catalog[0].find(M + 'Properties/' + M + 'Owners')
    if owners is None:
        raise ValueError('Control catalog has no Owners property')
    if variant == 'reference_owner':
        E.SubElement(owners, X + 'Item', {I + 'type': 'xr:MDObjectRef'}).text = 'ChartOfCharacteristicTypes.' + CHART
    _save(catalog_path, catalog, opening)

    chart_path = src / 'ChartsOfCharacteristicTypes' / (CHART + '.xml')
    chart, opening = _load(chart_path)
    props = chart[0].find(M + 'Properties')
    props.find(M + 'CharacteristicExtValues').text = 'Catalog.' + CATALOG
    types = props.find(M + 'Type')
    E.SubElement(types, V + 'Type').text = 'cfg:CatalogRef.' + CATALOG
    _save(chart_path, chart, opening)

    path = src / 'InformationRegisters/BenchPropertyValues.xml'
    register, opening = _load(path)
    resources = register[0].find(M + 'ChildObjects').findall(M + 'Resource')
    value = next(r for r in resources if r.find(M + 'Properties/' + M + 'Name').text == 'Value')
    typ = value.find(M + 'Properties/' + M + 'Type')
    if variant == 'typeset_no_owner':
        typ.clear()
        E.SubElement(typ, V + 'TypeSet').text = 'cfg:Characteristic.' + CHART
    elif variant in ('reference_owner', 'reference_no_owner'):
        typ.clear()
        E.SubElement(typ, V + 'Type').text = 'cfg:CatalogRef.' + CATALOG
    elif variant == 'unsupported':
        typ.clear()
        E.SubElement(typ, V + 'Type').text = 'xs:boolean'
    _save(path, register, opening)


def input_values(observation):
    """Return the two values actually read from the information register."""
    rows = observation.get('snapshots', {}).get('props', [])
    return sorted((r.get('property'), r.get('value')) for r in rows
                  if r.get('characteristic') == 'BENCH_Производитель')


def run(starter_source, starter_dt, binary, root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    specs = [('plain_string', None), ('typeset_no_owner', None),
             ('typeset_no_owner', 'statement_without_characteristics'),
             ('reference_owner', None), ('reference_no_owner', None), ('unsupported', None)]
    controls = []
    for variant, mutant in specs:
        label = variant + ('_missing_grouping' if mutant else '')
        folder = root / label
        folder.mkdir()
        src = folder / 'src'
        binding = generate(starter_source, src, 'one', mutant)
        configure(src, variant)
        before = tree_manifest(src)
        result = grade(src, binding, starter_dt, binary, folder / 'grade', ['ou_report'])
        verdicts = {r['id']: r['verdict'] for r in result['rules'] if r['id'] in ('OU04', 'OU19', 'OU20', 'OU21')}
        observation = result['observations'].get('ou_report', {})
        values = input_values(observation)
        expected = [('BENCH_P1', 'Alpha'), ('BENCH_P2', 'Beta')]
        observation_errors = observation.get('errors', {})
        if variant == 'unsupported':
            passed = (not result['errors']
                      and 'Нет поддерживаемого типа значения характеристики' in str(observation_errors.get('characteristic', ''))
                      and verdicts.get('OU04') == 'inconclusive' and verdicts.get('OU20') == 'inconclusive')
        else:
            passed = (not result['errors'] and not observation_errors and values == expected
                      and verdicts.get('OU04') == 'pass' and verdicts.get('OU19') == 'pass'
                      and verdicts.get('OU21') == 'pass'
                      and verdicts.get('OU20') == ('fail' if mutant else 'pass'))
        passed = bool(passed and tree_manifest(src) == before)
        controls.append({'case': label, 'passed': passed, 'values': values,
                         'verdicts': verdicts, 'errors': result['errors'],
                         'observation_errors': observation_errors})
    from .calibration_characteristics_forms import run as calibrate_forms
    form_calibration = calibrate_forms(starter_source, starter_dt, binary, root / 'forms')
    summary = {'passed': all(c['passed'] for c in controls) and form_calibration['passed'],
               'controls': controls, 'forms': form_calibration}
    write_json(root / 'summary.json', summary)
    return summary
