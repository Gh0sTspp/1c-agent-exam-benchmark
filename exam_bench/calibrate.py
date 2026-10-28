"""Real 1C calibration is a prerequisite to paid exam attempts."""
import copy,json
from pathlib import Path
from .calibration import generate
from .common import digest,write_json,grading_fingerprint,runtime_fingerprint,tree_manifest
from .grader import grade,compare,PROFILE


def calibrate(starter_source,starter_dt,binary,root,fail_fast=False):
    from .runtime import machine_identity, require_execution_mode, platform_binary
    require_execution_mode()
    if str(Path(binary).resolve())!=platform_binary():
        raise ValueError('Calibration binary must match the machine settings')
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    implementation=grading_fingerprint()
    write_json(root/'implementation.json',implementation)
    positives=[];negatives=[];baseline=None
    for variant in ('one','two','sub','tab'):
        folder=root/variant;folder.mkdir();b=generate(starter_source,folder/'src',variant)
        for path in (folder/'src').rglob('*'):
            if path.is_file():path.chmod(0o444)
        source_hashes=tree_manifest(folder/'src')
        previous=None
        for repetition in (1,2):
            g=grade(folder/'src',b,starter_dt,binary,folder/f'grade-{repetition}')
            passed=g['status']=='partial_pass'
            same=previous is None or previous==g['observations']
            if tree_manifest(folder/'src')!=source_hashes:raise ValueError('Calibration source was modified')
            positives.append({'variant':variant,'repetition':repetition,'grade_ref':str((folder/f'grade-{repetition}'/'grade.json').relative_to(root)),'passed':passed,'same_observations_as_prior':same})
            write_json(root/'progress.json',{'phase':'positive','variant':variant,'repetition':repetition,'positives':positives,'negatives':negatives,'errors':g['errors']})
            if fail_fast and (not passed or not same):raise ValueError('Positive calibration failed: '+variant+' repetition '+str(repetition))
            previous=g['observations']
            if variant=='one' and repetition==1:baseline=(g,b)
            print('positive',variant,repetition,g['status'],'repeat_identical',same,flush=True)
    for mutation,cases,rule in [('warehouse_average',['average'],'BU13'),('ignore_manual',['manual'],'BU02'),('double_analog',['shared_short','shared_enough'],'BU12'),('partial_refusal',['oversell','shared_short'],'BU10'),('posting_crash',['oversell','shared_short','average','shared_enough'],'BU10'),
                                ('no_transitive',['chain'],'BU03'),('analog_first',['own_first'],'BU08'),('article_desc',['order'],'BU11'),
                                ('no_substitution',['shared_enough'],'BU09'),('company_stock',['oversell','average'],'BU06'),
                                ('no_revenue',['average'],'BU15'),('cost_wrong_debit',['average'],'BU14'),('receipt_wrong_credit',['average'],'BU07'),
                                ('manual_restricted',['manual'],'BU01'),('article_overwrite',['order'],'BU04'),('warehouse_in_rows',['average'],'BU05'),
                                ('report_ignores_period',['report'],'BU16'),('report_profit_wrong',['report'],'BU17'),
                                ('fifo_as_lifo',['ou_policies'],'OU15'),('lifo_as_fifo',['ou_policies'],'OU16'),('average_as_fifo',['ou_policies'],'OU17'),
                                ('policy_global',['ou_policies'],'OU02'),('department_first_row',['ou_policies'],'OU18'),('department_in_header',['ou_policies'],'OU14'),
                                ('disassembly_doc',['ou_policies'],'OU06'),('assembly_no_movements',['ou_policies','ou_assembly'],'OU01'),('target_ignored',['ou_assembly'],'OU10'),
                                ('spec_ignored',['ou_assembly'],'OU11'),('extras_ignored',['ou_assembly','ou_assembly_split'],'OU11'),('property_ignored',['ou_assembly'],'OU13'),
                                ('spec_first_version',['ou_history'],'OU12'),('policy_latest',['ou_history'],'OU03'),('spec_nonperiodic',['ou_history'],'OU08'),
                                ('statement_ignores_department',['ou_report'],'OU19'),('statement_without_characteristics',['ou_report'],'OU20'),('ou_sales_profit_wrong',['ou_report'],'OU21'),
                                ('parttime_merged',['pr_tariff'],'PR02'),('schedule_common',['pr_tariff'],'PR03'),('rate_times_days',['pr_tariff'],'PR04'),
                                ('rates_monthly',['pr_tariff'],'PR05'),('rate_no_history',['pr_tariff'],'PR18'),('rate_at_month_end',['pr_tariff'],'PR06'),('one_month_unchecked',['pr_tariff'],'PR16'),
                                ('doc_date_period',['pr_tariff'],'PR18'),('mixed_kinds_refused',['pr_tariff','pr_bonus'],'PR15'),
                                ('trip_displaces_whole_month',['pr_trip'],'PR01'),('no_displacement',['pr_trip','pr_bonus'],'PR10'),('bonus_not_displaced',['pr_trip','pr_bonus'],'PR10'),
                                ('trip_calendar_days',['pr_trip'],'PR11'),('trip_rate_wrong_months',['pr_trip'],'PR12'),('cross_month_refused',['pr_trip'],'PR17'),
                                ('no_backdate',['pr_trip','pr_backdate'],'PR13'),('bonus_includes_head',['pr_bonus'],'PR07'),('bonus_current_month',['pr_bonus'],'PR07'),
                                ('scale_hardcoded',['pr_bonus'],'PR08'),('seniority_from_accounting',['pr_bonus'],'PR09'),('bonus_report_all_months',['pr_bonus'],'PR19'),
                                ('form_no_manager',['forms'],'F01'),('list_truncated',['forms'],'F02'),('list_not_chart',['forms'],'F03'),('fields_all',['forms'],'F04'),('values_not_saved',['forms'],'F05'),
                                ('interface_one_section',['manual'],'G01'),('register_hidden',['manual'],'G02'),('mixed_group',['manual'],'G03')]:
        folder=root/mutation;folder.mkdir();b=generate(starter_source,folder/'src','one',mutation)
        for path in (folder/'src').rglob('*'):
            if path.is_file():path.chmod(0o444)
        source_hashes=tree_manifest(folder/'src')
        g=grade(folder/'src',b,starter_dt,binary,folder/'grade',cases)
        if tree_manifest(folder/'src')!=source_hashes:raise ValueError('Calibration source was modified')
        verdict=next(r['verdict'] for r in g['rules'] if r['id']==rule)
        negatives.append({'mutation':mutation,'rule':rule,'grade_ref':str((folder/'grade'/'grade.json').relative_to(root)),'target_verdict':verdict,'runtime_observations_available':all(c in g['observations'] for c in cases),'syntax_or_adapter_errors':bool(g['errors'])})
        write_json(root/'progress.json',{'phase':'mutation','mutation':mutation,'positives':positives,'negatives':negatives,'errors':g['errors']})
        if fail_fast and (verdict!='fail' or not negatives[-1]['runtime_observations_available'] or g['errors']):raise ValueError('Mutation calibration failed: '+mutation)
        print('mutation',mutation,verdict,g['errors'],flush=True)
    # A pure invariant check proves rejection of an unposted document that leaks
    # movements; normal 1C transactions roll handler writes back on refusal.
    g,b=baseline
    leaked=copy.deepcopy(g['observations']);leaked['oversell']['after'].append(copy.deepcopy(leaked['average']['after'][-1]));leaked['oversell']['all_after']['injected_leak']=['changed']
    leak_check=next(r for r in compare(leaked,b) if r['id']=='BU10')['verdict']=='fail'
    from .calibration_query import run as calibrate_query
    query_calibration=calibrate_query(starter_source,starter_dt,binary,root/'query-parameter')
    from .calibration_periodicity import run as calibrate_periodicity
    periodicity_calibration=calibrate_periodicity(starter_source,starter_dt,binary,root/'periodicity')
    from .calibration_characteristics import run as calibrate_characteristics
    characteristics_calibration=calibrate_characteristics(starter_source,starter_dt,binary,root/'characteristics')
    accepted=all(p['passed'] and p['same_observations_as_prior'] for p in positives) and all(n['target_verdict']=='fail' and n['runtime_observations_available'] and not n['syntax_or_adapter_errors'] for n in negatives) and leak_check and query_calibration['passed'] and periodicity_calibration['passed'] and characteristics_calibration['passed']
    if implementation!=grading_fingerprint():raise ValueError('Grading implementation changed during calibration')
    summary={'schema_version':1,'profile_id':PROFILE['id'],'grader_sha256':digest(Path(__file__).parent/'grader.py'),'calibration_generator_sha256':digest(Path(__file__).parent/'calibration.py'),'accepted':accepted,'positives':positives,'negatives':negatives,'unposted_movement_leak_oracle_check':leak_check,'limitations':['partial_refusal native mutant posts incomplete expense instead of refusing; an actual leak after refusal is checked on controlled observation data because native posting transaction rolls writes back','BU02 reports and other readers are not checked','ledger item/warehouse as physical dimensions (variants one, two) or predefined subconto kinds (variant sub); analogs as an information register pair or a tabular section of the items catalog (variant tab); indexed СубконтоДтN bindings and other analog storage modes not supported yet','OU04, OU05, OU07, OU09 have no dedicated mutant: they are checked by positives only','PR14: metadata and code signs alone do not prove runtime use (A08); the old unreachable recalculation_sign mutant is excluded, operative-path detection remains uncalibrated'],'models_probed':[],'model_probe_ref':None}
    summary.update(fingerprint_version=2,runtime_implementation_files=runtime_fingerprint(),implementation_files=implementation,readonly_sources_verified=True,machine=machine_identity())
    summary['query_parameter_calibration']=query_calibration
    summary['periodicity_calibration']=periodicity_calibration
    summary['characteristics_calibration']=characteristics_calibration
    write_json(root/'summary.json',summary)
    return summary
