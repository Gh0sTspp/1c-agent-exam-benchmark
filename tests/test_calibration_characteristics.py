import tempfile
import unittest
import xml.etree.ElementTree as E
from pathlib import Path

from exam_bench.calibration_characteristics import CATALOG, CHART, I, M, V, X, configure, input_values


OPENING = ('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" '
           'xmlns:v8="http://v8.1c.ru/8.1/data/core" '
           'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
           'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">')


def fixture(root):
    def put(path, body):
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(OPENING + body + '</MetaDataObject>', encoding='utf-8')
    put('Configuration.xml', '<Configuration><ChildObjects></ChildObjects></Configuration>')
    put('Catalogs/Валюты.xml', '<Catalog uuid="00000000-0000-0000-0000-000000000000"><Properties>'
        '<Name>Валюты</Name><Owners/></Properties><ChildObjects/></Catalog>')
    put('ChartsOfCharacteristicTypes/СвойстваОбъектов.xml', '<ChartOfCharacteristicTypes><Properties>'
        '<Name>СвойстваОбъектов</Name><CharacteristicExtValues/><Type><v8:Type>xs:string</v8:Type>'
        '</Type></Properties></ChartOfCharacteristicTypes>')
    put('InformationRegisters/BenchPropertyValues.xml', '<InformationRegister><ChildObjects>'
        '<Resource><Properties><Name>Value</Name><Type><v8:Type>xs:string</v8:Type></Type>'
        '</Properties></Resource></ChildObjects></InformationRegister>')


class CharacteristicCalibrationTests(unittest.TestCase):
    def test_typeset_without_owner_matches_real_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); fixture(root); configure(root, 'typeset_no_owner')
            chart = E.parse(root / f'ChartsOfCharacteristicTypes/{CHART}.xml').getroot()[0]
            self.assertEqual(chart.find(M+'Properties/'+M+'CharacteristicExtValues').text, 'Catalog.'+CATALOG)
            self.assertEqual([v.text for v in chart.findall(M+'Properties/'+M+'Type/'+V+'Type')],
                             ['xs:string', 'cfg:CatalogRef.'+CATALOG])
            reg = E.parse(root / 'InformationRegisters/BenchPropertyValues.xml').getroot()[0]
            self.assertEqual(reg.find('.//'+M+'Resource/'+M+'Properties/'+M+'Type/'+V+'TypeSet').text,
                             'cfg:Characteristic.'+CHART)
            catalog = E.parse(root / f'Catalogs/{CATALOG}.xml').getroot()[0]
            self.assertEqual(len(catalog.find(M+'Properties/'+M+'Owners')), 0)

    def test_reference_owner_is_explicit_and_resource_rejects_string(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); fixture(root); configure(root, 'reference_owner')
            catalog = E.parse(root / f'Catalogs/{CATALOG}.xml').getroot()[0]
            owner = catalog.find(M+'Properties/'+M+'Owners/'+X+'Item')
            self.assertEqual(owner.text, 'ChartOfCharacteristicTypes.'+CHART)
            self.assertEqual(owner.get(I+'type'), 'xr:MDObjectRef')
            reg = E.parse(root / 'InformationRegisters/BenchPropertyValues.xml').getroot()[0]
            self.assertEqual(reg.find('.//'+M+'Resource/'+M+'Properties/'+M+'Type/'+V+'Type').text,
                             'cfg:CatalogRef.'+CATALOG)

    def test_both_characteristic_values_are_observed(self):
        observation = {'snapshots': {'props': [
            {'property': 'BENCH_P2', 'characteristic': 'BENCH_Производитель', 'value': 'Beta'},
            {'property': 'BENCH_P1', 'characteristic': 'BENCH_Производитель', 'value': 'Alpha'},
            {'property': 'BENCH_P1', 'characteristic': 'Other', 'value': 'ignored'}]}}
        self.assertEqual(input_values(observation), [('BENCH_P1', 'Alpha'), ('BENCH_P2', 'Beta')])
        observation['snapshots']['props'].pop(1)
        self.assertNotEqual(input_values(observation), [('BENCH_P1', 'Alpha'), ('BENCH_P2', 'Beta')])


if __name__ == '__main__':
    unittest.main()
