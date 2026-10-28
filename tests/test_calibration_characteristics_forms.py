import tempfile
import unittest
import xml.etree.ElementTree as E
from pathlib import Path

from exam_bench.calibration_characteristics import CHART, M, V
from exam_bench.calibration_characteristics_forms import configure_form
from test_calibration_characteristics import OPENING, fixture


def form_fixture(root):
    fixture(root)
    chart = root / f'ChartsOfCharacteristicTypes/{CHART}.xml'
    text = chart.read_text(encoding='utf-8').replace('</Type>', '<v8:StringQualifiers>'
        '<v8:Length>10</v8:Length><v8:AllowedLength>Variable</v8:AllowedLength>'
        '</v8:StringQualifiers></Type>')
    chart.write_text(text, encoding='utf-8')
    catalog = root / 'Catalogs/Контрагенты.xml'
    catalog.write_text(OPENING + '<Catalog><ChildObjects><TabularSection><Properties><Name>Сведения</Name>'
        '</Properties><ChildObjects><Attribute><Properties><Name>Значение</Name><Type>'
        '<v8:Type>xs:string</v8:Type></Type></Properties></Attribute></ChildObjects></TabularSection>'
        '</ChildObjects></Catalog></MetaDataObject>', encoding='utf-8')
    module = root / 'Catalogs/Контрагенты/Forms/Форма/Ext/Form/Module.bsl'
    module.parent.mkdir(parents=True)
    module.write_text('Новый ОписаниеТипов("Строка", , Новый КвалификаторыСтроки(50))', encoding='utf-8')


class DynamicCharacteristicFormTests(unittest.TestCase):
    def test_positive_uses_chart_type_for_field_and_value_storage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); form_fixture(root); configure_form(root, 'positive')
            text = (root / 'Catalogs/Контрагенты/Forms/Форма/Ext/Form/Module.bsl').read_text(encoding='utf-8')
            self.assertEqual(text, 'С.Свойство.ТипЗначения')
            catalog = E.parse(root / 'Catalogs/Контрагенты.xml').getroot()[0]
            self.assertEqual(catalog.find('.//'+M+'TabularSection/'+M+'ChildObjects/'+M+'Attribute/'
                             +M+'Properties/'+M+'Type/'+V+'TypeSet').text, 'cfg:Characteristic.'+CHART)

    def test_negative_metadata_controls_are_distinct(self):
        for variant in ('reference_only', 'short_string'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as td:
                root = Path(td); form_fixture(root); configure_form(root, variant)
                chart = E.parse(root / f'ChartsOfCharacteristicTypes/{CHART}.xml').getroot()[0]
                types = chart.find(M+'Properties/'+M+'Type')
                if variant == 'reference_only':
                    self.assertNotIn('xs:string', [x.text for x in types.findall(V+'Type')])
                    self.assertIsNone(types.find(V+'StringQualifiers'))
                else:
                    self.assertEqual(types.find(V+'StringQualifiers/'+V+'Length').text, '2')


if __name__ == '__main__':
    unittest.main()
