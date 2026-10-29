import unittest

from exam_bench import ou


def binding():
    return {'ou': {'objects': {'characteristics': 'ChartOfCharacteristicTypes.Kinds',
                               'property_values': 'InformationRegister.Values'},
                   'fields': {'sale': {'department': 'Rows.Department'}}}}


def checks(report):
    return {r['id']: r for r in ou.compare({'ou_report': report}, binding())}


class CharacteristicFixtureTests(unittest.TestCase):
    def test_unsupported_type_does_not_become_solution_penalty(self):
        result = checks({'errors': {'characteristic': 'Нет поддерживаемого типа значения характеристики'},
                         'snapshots': {}})
        self.assertEqual(result['OU04']['verdict'], 'inconclusive')
        self.assertEqual(result['OU20']['verdict'], 'inconclusive')

    def test_mangled_or_missing_values_are_inconclusive_not_fail(self):
        for rows in ([], [{'property': 'BENCH_P1', 'characteristic': 'BENCH_Производитель', 'value': 'Alph'},
                          {'property': 'BENCH_P2', 'characteristic': 'BENCH_Производитель', 'value': 'Beta'}]):
            with self.subTest(rows=rows):
                result = checks({'errors': {}, 'snapshots': {'props': rows, 'statement': []}})
                self.assertEqual(result['OU04']['verdict'], 'inconclusive')
                self.assertEqual(result['OU20']['verdict'], 'inconclusive')

    def test_valid_values_are_proved_by_readback(self):
        rows = [{'property': 'BENCH_P1', 'characteristic': 'BENCH_Производитель', 'value': 'Alpha'},
                {'property': 'BENCH_P2', 'characteristic': 'BENCH_Производитель', 'value': 'Beta'}]
        result = checks({'errors': {}, 'snapshots': {'props': rows, 'statement': []}})
        self.assertEqual(result['OU04']['verdict'], 'pass')
        # The data input was verified, but no report binding or column schema
        # was provided, so the report itself cannot be judged from this fixture.
        self.assertEqual(result['OU20']['verdict'], 'inconclusive')

    def test_catalog_values_get_unique_codes_and_string_qualifier_is_a_property(self):
        code = ou.ou_characteristic_code('ChartOfCharacteristicTypes.Kinds', 'InformationRegister.Values', 'Value')
        self.assertIn('Эл.Наименование = Текст; Эл.УстановитьНовыйКод();', code)
        self.assertIn('МД.Тип.КвалификаторыСтроки)', code)
        self.assertNotIn('МД.Тип.КвалификаторыСтроки()', code)

    def test_forms_keep_their_independent_legacy_helper(self):
        self.assertIn('Функция НовыйВидХарактеристики', ou.characteristic_code('ChartOfCharacteristicTypes.Kinds'))
        self.assertIn('РегистрыСведений.Values', ou.ou_characteristic_code(
            'ChartOfCharacteristicTypes.Kinds', 'InformationRegister.Values', 'Value'))


if __name__ == '__main__':
    unittest.main()
