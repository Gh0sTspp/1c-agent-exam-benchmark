import unittest

from exam_bench import forms


def binding(kind='table'):
    values = ({'kind': 'table', 'characteristic': 'Info.Kind', 'value': 'Info.Value'}
              if kind == 'table' else
              {'kind': 'register', 'register': 'InformationRegister.Values', 'counterparty': 'Person',
               'characteristic': 'Kind', 'value': 'Value'})
    return {'forms': {'objects': {'counterparties': 'Catalog.People', 'managers': 'Catalog.Managers',
                                   'characteristics': 'ChartOfCharacteristicTypes.Kinds'},
                      'fields': {'counterparties': {'manager': 'Manager'}, 'managers': {'list': 'Kinds.Kind'}},
                      'values': values}}


def verdict(observation, rule='F05'):
    static = {'manager_field': 'present', 'chart': 'Kinds', 'list_types': ['ChartOfCharacteristicTypesRef.Kinds']}
    return next(r for r in forms.compare({'forms': observation}, binding(), static) if r['id'] == rule)


class FormsCharacteristicInputTests(unittest.TestCase):
    def test_unsupported_or_truncated_input_is_inconclusive(self):
        for message in ('no string type', 'string length is too short'):
            with self.subTest(message=message):
                result = verdict({'fixture_error': message})
                self.assertEqual(result['verdict'], 'inconclusive')
                self.assertIn('fixture unavailable', result['reason'])

    def test_failed_storage_after_valid_input_remains_fail(self):
        result = verdict({'forms': {'saved': {'typed': ['C1', 'C2'], 'written': True, 'stored': []}}})
        self.assertEqual(result['verdict'], 'fail')

    def test_unconfirmed_input_and_write_do_not_pass_or_charge(self):
        stored = [{'kind': 'BENCH_Валюта', 'value': 'USD'}, {'kind': 'BENCH_Срок', 'value': '15'}]
        cases = [
            {'typed': ['C1'], 'written': True, 'stored': stored},
            {'typed': [], 'written': True, 'stored': stored},
            {'written': True, 'stored': stored},
            {'typed': ['C1', 'C2'], 'written': False, 'stored': stored},
            {'typed': ['C1', 'C2'], 'stored': stored},
            {'error': 'write did not complete'},
        ]
        for saved in cases:
            with self.subTest(saved=saved):
                self.assertEqual(verdict({'forms': {'saved': saved}})['verdict'], 'inconclusive')

    def test_successful_storage_after_valid_input_is_pass(self):
        stored = [{'kind': 'BENCH_Валюта', 'value': 'USD'}, {'kind': 'BENCH_Срок', 'value': '15'}]
        result = verdict({'forms': {'saved': {'typed': ['C1', 'C2'], 'written': True, 'stored': stored}}})
        self.assertEqual(result['verdict'], 'pass')

    def test_both_storage_modes_use_the_selected_field(self):
        table = forms.forms_characteristic_code(binding('table')['forms'])
        register = forms.forms_characteristic_code(binding('register')['forms'])
        self.assertIn('ТабличныеЧасти.Найти("Info")', table)
        self.assertIn('ТЧ.Реквизиты.Найти("Value")', table)
        self.assertIn('РегистрыСведений.Values', register)
        self.assertIn('РегистрМД.Ресурсы.Найти("Value")', register)
        for source in (table, register):
            self.assertIn('МД.Тип.СодержитТип(Тип("Строка"))', source)
            self.assertIn('ПолеМД.Тип.СодержитТип(Тип("Строка"))', source)
            self.assertIn('МД.Тип.КвалификаторыСтроки', source)
            self.assertIn('СтрРазделить("USD,15", ",")', source)


if __name__ == '__main__':
    unittest.main()
