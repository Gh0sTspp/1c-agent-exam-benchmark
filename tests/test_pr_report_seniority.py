from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from exam_bench import pr, submission


def fixture(unit):
    fields = {name: name for name in ('employee', 'seniority', 'percent', 'amount')}
    report = {'fields': fields, 'seniority_unit': unit}
    binding = {'reports': {'pr_bonus': report}}
    case = pr.CASES['pr_bonus']
    month = pr.D(2025, 2, 1)
    model = pr.model(case)
    values = {'years': {'H': Decimal('2.15'), 'G': Decimal('5.15'), 'K': Decimal('0.15')},
              'months': {'H': 25, 'G': 61, 'K': 1},
              'days': {'H': 780, 'G': 1880, 'K': 58}}
    rows = []
    for person, dept in (('H', 'A'), ('G', 'B'), ('K', 'C')):
        amount = sum((v for (e, d, role, m), v in model.items()
                      if e == person and d == dept and role == 'bonus' and m == month), Decimal(0))
        rows.append({'employee': 'BENCH_' + person, 'seniority': values[unit][person],
                     'percent': pr.bonus_percent(case, person, month), 'amount': amount})
    observation = {'pr_bonus': {'errors': {}, 'snapshots': {'report_feb': rows,
                           'report_feb_schema': {'columns': list(fields.values())}}}}
    return binding, observation


def verdict(binding, observation):
    return next(r for r in pr.compare(observation, binding) if r['id'] == 'PR19')['verdict']


class SeniorityReportTests(unittest.TestCase):
    def test_known_units_accept_correct_numeric_seniority(self):
        for unit in ('years', 'months', 'days'):
            with self.subTest(unit=unit):
                binding, observations = fixture(unit)
                self.assertEqual(verdict(binding, observations), 'pass')

    def test_obviously_wrong_seniority_fails(self):
        for unit in ('years', 'months', 'days'):
            binding, observations = fixture(unit)
            observations['pr_bonus']['snapshots']['report_feb'][0]['seniority'] = 9999
            self.assertEqual(verdict(binding, observations), 'fail')

    def test_unknown_unit_or_missing_mapping_is_inconclusive(self):
        binding, observations = fixture('years')
        del binding['reports']['pr_bonus']['seniority_unit']
        self.assertEqual(verdict(binding, observations), 'inconclusive')
        binding['reports']['pr_bonus']['seniority_unit'] = 'years'
        del binding['reports']['pr_bonus']['fields']['seniority']
        self.assertEqual(verdict(binding, observations), 'inconclusive')

    def test_unknown_unit_does_not_hide_a_proven_wrong_amount(self):
        binding, observations = fixture('years')
        del binding['reports']['pr_bonus']['seniority_unit']
        observations['pr_bonus']['snapshots']['report_feb'][0]['amount'] = 999999
        self.assertEqual(verdict(binding, observations), 'fail')

    def test_null_is_not_zero_and_text_is_inconclusive(self):
        binding, observations = fixture('years')
        rows = observations['pr_bonus']['snapshots']['report_feb']
        rows[2]['seniority'] = None
        self.assertEqual(verdict(binding, observations), 'fail')
        rows[2]['seniority'] = '1 месяц'
        self.assertEqual(verdict(binding, observations), 'inconclusive')

    def test_user_report_unit_survives_binding_validation(self):
        binding, _ = fixture('months')
        report = binding['reports']['pr_bonus']
        report.update({'object': 'Report.Bonus', 'kind': 'dcs',
                       'parameters': {'period': 'Period'}})
        cleaned, _ = submission.strip_extras(binding)
        self.assertEqual(cleaned['reports']['pr_bonus']['seniority_unit'], 'months')
        root = ET.Element('Report')
        props = ET.SubElement(root, submission.MD + 'Properties')
        ET.SubElement(props, submission.MD + 'MainDataCompositionSchema').text = 'Report.Bonus.Template.Main'
        with patch.object(submission, 'descriptor', return_value=root):
            submission.check_report(Path('.'), 'pr_bonus', cleaned['reports']['pr_bonus'])
        self.assertEqual(cleaned['reports']['pr_bonus']['seniority_unit'], 'months')


if __name__ == '__main__':
    unittest.main()
