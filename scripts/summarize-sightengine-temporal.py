#!/usr/bin/env python3
"""Apply frozen acceptance to a completed local receipt; never calls an API."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_SHA = '1374a18b17699d6aef0ef0868b21f9f580bdbaa667f26caa45d92d0dcacc25b7'
RUNNER_SHA = '7a9c3412fdc7d3505b4643204bebe0c3dcf6a1dc32368f598b2e126151fb04a7'
AGGREGATOR_SHA = '527b15281583255c975c60b7f8f3b44981c2a6744a6ab4af514bc61b667a7453'
HELPER_SHA = 'b953a1dd11f3f2b5bf81f3c9d7819466fed1d98c7defeb234e0439c82ca852be'
AI = 'persistent_ai_indicators'
CLEAR = 'no_clear_indicators'
INC = 'inconclusive'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strict_json(path):
    return json.loads(Path(path).read_bytes(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON')))


def get_aggregator():
    path = ROOT / 'scripts/sightengine-temporal-evidence.py'
    if sha(path) != AGGREGATOR_SHA:
        raise ValueError('Frozen aggregator source mismatch')
    spec = importlib.util.spec_from_file_location('frozen_temporal_summary', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fraction(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'fraction': numerator / denominator if denominator else None}


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def counts(rows):
    return {'total': len(rows), **{key: sum(r['decision'] == key for r in rows)
            for key in [AI, CLEAR, INC, 'technical_error', 'not_attempted']},
            'casesWithIsolatedAlerts': sum(r['isolatedAlertCount'] > 0 for r in rows),
            'isolatedAlerts': sum(r['isolatedAlertCount'] for r in rows),
            'reviewRequiredCases': sum(r['reviewRequired'] for r in rows)}


def analyze(manifest, receipt, aggregator):
    """Pure result analysis. Identity/media-source verification belongs to main."""
    cases = manifest['cases']
    results = receipt.get('results')
    if not isinstance(results, list) or len(results) != len(cases):
        raise ValueError('Receipt must retain every planned case, including unattempted cases')
    if len({r.get('id') for r in results}) != len(results):
        raise ValueError('Duplicate receipt case IDs')
    if {r.get('id') for r in results} != {c['id'] for c in cases}:
        raise ValueError('Receipt case set differs from frozen manifest')
    actual = {r['id']: r for r in results}
    rows = []
    observed_operations = 0
    for index, case in enumerate(cases):
        result = actual[case['id']]
        if result['status'] == 'not_attempted':
            rows.append({'id': case['id'], 'parentId': case['parentId'], 'cohort': case['cohort'],
                         'label': case['label'], 'generator': case['generator'], 'quality': case['quality'],
                         'labelEvidenceStrength': case['labelEvidenceStrength'], 'decision': 'not_attempted',
                         'technicalComplete': False, 'isolatedAlertCount': 0, 'reviewRequired': False,
                         'persistentRuns': [], 'isolatedAlerts': [], 'elapsedSeconds': None,
                         'reportedOperations': None, 'reason': result.get('reason')})
            continue
        if result.get('index') != index or result.get('mediaSha256') != case['sha256']:
            raise ValueError('Case index or media identity mismatch')
        response = result.get('response', {})
        evidence = response.get('evidence', {})
        if not isinstance(evidence, dict):
            evidence = {}
        reported = evidence.get('request', {}).get('operations')
        valid_accounting = type(reported) is int and reported >= 0
        if valid_accounting:
            observed_operations += reported
        if result.get('reportedOperationsObserved') != observed_operations:
            raise ValueError('Cumulative operation ledger mismatch')
        complete = (response.get('kind') == 'response' and evidence.get('schemaValid') is True
                    and evidence.get('coverageComplete') is True and valid_accounting)
        computed = aggregator.aggregate_evidence(evidence.get('frames', []),
            duration_seconds=case['media']['durationSeconds'], technical_complete=complete,
            declared_interval_seconds=0.5)
        if computed != result.get('temporal'):
            raise ValueError('Saved temporal result differs from frozen recomputation')
        terminal_complete = (result['status'] == 'completed' and computed['technicalComplete']
                             and result.get('accountingMayBeIncomplete') is False
                             and result.get('transmissionMayBeUncertain') is False)
        decision = computed['verdict'] if terminal_complete else 'technical_error'
        elapsed = result.get('elapsedSeconds')
        if type(elapsed) not in (float, int) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('Invalid case elapsed time')
        rows.append({'id': case['id'], 'parentId': case['parentId'], 'cohort': case['cohort'],
                     'label': case['label'], 'generator': case['generator'], 'quality': case['quality'],
                     'labelEvidenceStrength': case['labelEvidenceStrength'], 'decision': decision,
                     'technicalComplete': terminal_complete,
                     'isolatedAlertCount': len(computed['isolatedAlerts']),
                     'reviewRequired': computed['reviewRequired'], 'persistentRuns': computed['persistentRuns'],
                     'isolatedAlerts': computed['isolatedAlerts'], 'elapsedSeconds': elapsed,
                     'reportedOperations': reported if valid_accounting else None,
                     'technicalIssues': computed['technicalIssues'] + computed['coverage']['issues']})
    if receipt.get('reportedOperationsObserved') != observed_operations:
        raise ValueError('Final operation ledger mismatch')

    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['cohort'], row['parentId'])].append(row)
    parents = []
    for (cohort, parent), members in sorted(grouped.items()):
        technical_failure = any(not r['technicalComplete'] for r in members)
        persistent_alert = any(r['decision'] == AI for r in members)
        decision = ('technical_error' if technical_failure else AI if persistent_alert
                    else INC if any(r['decision'] == INC for r in members) else CLEAR)
        parents.append({'cohort': cohort, 'parentId': parent, 'decision': decision,
                        'hasPersistentAlert': persistent_alert, 'technicalFailure': technical_failure,
                        'fileIds': [r['id'] for r in members], 'fileDecisions': [r['decision'] for r in members],
                        'casesWithIsolatedAlerts': sum(r['isolatedAlertCount'] > 0 for r in members),
                        'isolatedAlertCount': sum(r['isolatedAlertCount'] for r in members)})

    publisher = [r for r in rows if r['cohort'] == 'publisher_assigned_ai']
    negatives = [r for r in rows if r['cohort'] == 'documented_negative']
    direct = [r for r in rows if r['cohort'] == 'receipt_backed_same_parent_check']
    neg_parents = [r for r in parents if r['cohort'] == 'documented_negative']
    by_quality = {}
    for quality in manifest['acceptance']['publisherAssignedAi']['perQuality']:
        qrows = [r for r in publisher if r['quality'] == quality]
        by_quality[quality] = {**counts(qrows), 'recall': fraction(sum(r['decision'] == AI for r in qrows), len(qrows))}
    gates = {}
    acceptance = manifest['acceptance']
    gates['all_cases_technically_complete'] = (receipt.get('status') == 'completed'
        and receipt.get('stopReason') is None and all(r['technicalComplete'] for r in rows))
    gates['operation_cap'] = observed_operations <= manifest['limits']['maxReservedOperations']
    gates['reserved_accounting'] = observed_operations <= manifest['limits']['reservedOperations']
    n = acceptance['documentedNegative']
    gates['no_documented_negative_persistent_alerts'] = sum(r['decision'] == AI for r in negatives) <= n['maxPersistentAlerts']
    gates['negative_clear_file_coverage'] = sum(r['decision'] == CLEAR for r in negatives) >= n['minimumClearFiles']
    gates['negative_clear_parent_coverage'] = sum(r['decision'] == CLEAR for r in neg_parents) >= n['minimumClearParents']
    gates['publisher_assigned_ai_recall'] = sum(r['decision'] == AI for r in publisher) >= acceptance['publisherAssignedAi']['minimumPersistentAlerts']
    for quality, threshold in acceptance['publisherAssignedAi']['perQuality'].items():
        gates['publisher_assigned_ai_' + quality] = (by_quality[quality]['total'] == threshold['total']
            and by_quality[quality][AI] >= threshold['minimumPersistentAlerts'])
    gates['receipt_backed_same_parent_check'] = sum(r['decision'] == AI for r in direct) >= acceptance['receiptBackedSameParent']['minimumPersistentAlerts']
    latencies = [r['elapsedSeconds'] for r in rows if r['elapsedSeconds'] is not None]
    return {'schemaVersion': 1, 'passesFrozenGates': all(gates.values()), 'gates': gates,
            'failedGates': [name for name, passed in gates.items() if not passed],
            'overall': counts(rows),
            'publisherAssignedAi': {**counts(publisher),
                'unconditionalRecall': fraction(sum(r['decision'] == AI for r in publisher), len(publisher)),
                'byQuality': by_quality,
                'nonDetectionIds': [r['id'] for r in publisher if r['decision'] != AI]},
            'documentedNegative': {**counts(negatives), 'parents': len(neg_parents),
                'falseAlertFiles': fraction(sum(r['decision'] == AI for r in negatives), len(negatives)),
                'falseAlertParents': fraction(sum(r['hasPersistentAlert'] for r in neg_parents), len(neg_parents)),
                'clearFiles': fraction(sum(r['decision'] == CLEAR for r in negatives), len(negatives)),
                'clearParents': fraction(sum(r['decision'] == CLEAR for r in neg_parents), len(neg_parents)),
                'falseAlertIds': [r['id'] for r in negatives if r['decision'] == AI]},
            'receiptBackedSameParent': {**counts(direct), 'qualification': 'Previously consumed visual parent in a different encoding; not new-source accuracy.'},
            'operationsObserved': observed_operations,
            'latencySeconds': {'attempted': len(latencies), 'median': statistics.median(latencies) if latencies else None,
                              'p95Linear': percentile(latencies, .95), 'sumCaseElapsed': sum(latencies)},
            'sourceParents': parents, 'cases': rows,
            'limitations': ['Publisher-assigned recall is not receipt-backed or independently authenticated accuracy.',
                'Documented negatives represent six curated source parents with dependent variants; no population FPR or calibration claim.',
                'No verified new mixed-positive case, subsecond sensitivity test, or user-Reel inference in this cohort.',
                'All isolated alerts remain unresolved, including those accompanying a persistent run.',
                'A pass permits only the frozen narrow next-step decision; a failure cannot be rescued by threshold or case selection.']}


def markdown(summary):
    p, n, d = (summary[k] for k in ['publisherAssignedAi', 'documentedNegative', 'receiptBackedSameParent'])
    lines = ['# Frozen temporal screen: ' + ('PASS' if summary['passesFrozenGates'] else 'FAIL'), '',
        'The fixed acceptance criteria ' + ('passed.' if summary['passesFrozenGates'] else 'failed. No threshold or criterion changed.'), '',
        '| Cohort | Persistent AI alerts | No clear indicators | Inconclusive | Technical/unattempted |',
        '| --- | ---: | ---: | ---: | ---: |']
    for name, row in [('Publisher-assigned AI', p), ('Documented negatives', n), ('Same-parent receipted Veo', d)]:
        lines.append(f'| {name} | {row[AI]}/{row["total"]} | {row[CLEAR]} | {row[INC]} | {row["technical_error"] + row["not_attempted"]} |')
    lines += ['', f'Publisher-assigned unconditional recall: **{p[AI]}/{p["total"]}**. This denominator includes every abstention and non-detection.',
              'Quality: ' + ', '.join(f'{q} {v[AI]}/{v["total"]}' for q, v in p['byQuality'].items()) + '.',
              f'Documented-negative parent false alerts: **{n["falseAlertParents"]["numerator"]}/{n["parents"]}**; clear parent outcomes: **{n["clearParents"]["numerator"]}/{n["parents"]}**.',
              f'Unresolved isolated alerts: **{summary["overall"]["isolatedAlerts"]} samples in {summary["overall"]["casesWithIsolatedAlerts"]} cases**; retained even when a persistent run also exists.',
              f'Reported operations: **{summary["operationsObserved"]}**. Median case time {summary["latencySeconds"]["median"]:.2f}s; p95 {summary["latencySeconds"]["p95Linear"]:.2f}s.', '',
              'Failed gates: ' + (', '.join(summary['failedGates']) or 'none') + '.', '',
              '| Source parent | Cohort | Parent outcome | File outcomes | Isolated alerts |',
              '| --- | --- | --- | --- | ---: |']
    for parent in summary['sourceParents']:
        lines.append(f'| {parent["parentId"]} | {parent["cohort"]} | {parent["decision"]} | {", ".join(parent["fileDecisions"])} | {parent["isolatedAlertCount"]} |')
    lines += ['', 'Per-case generator, quality, misses, false alerts, unresolved timestamps and technical evidence are retained in `summary.json`.', '']
    lines += ['- ' + limit for limit in summary['limitations']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sha(args.manifest) != MANIFEST_SHA:
        raise ValueError('Only the frozen25-case manifest may be summarized')
    manifest = strict_json(args.manifest)
    if sha(ROOT / manifest['candidate']['path']) != manifest['candidate']['sha256']:
        raise ValueError('Frozen bound candidate changed')
    receipt_path = args.run / 'receipt.json'
    receipt = strict_json(receipt_path)
    if any(receipt.get(k) != v for k, v in [('manifestSha256', MANIFEST_SHA), ('runnerSha256', RUNNER_SHA),
           ('aggregatorSha256', AGGREGATOR_SHA), ('helperSha256', HELPER_SHA),
           ('policyFingerprint', manifest['policy']['policyFingerprint'])]):
        raise ValueError('Execution identity does not match frozen candidate')
    if strict_json(args.run / 'manifest.json') != manifest:
        raise ValueError('Run manifest snapshot differs')
    for result in receipt['results']:
        if result['status'] != 'not_attempted' and strict_json(args.run / f'case-{result["index"]:02d}.json') != result:
            raise ValueError('Individual case receipt differs from terminal receipt')
    summary = analyze(manifest, receipt, get_aggregator())
    args.output.mkdir(parents=True, exist_ok=False)
    source = {'manifest': {'path': str(args.manifest), 'sha256': sha(args.manifest)},
              'runReceipt': {'path': str(receipt_path), 'sha256': sha(receipt_path)},
              'summarizer': {'path': str(Path(__file__)), 'sha256': sha(__file__)}}
    summary['sources'] = source
    summary['summarizedAt'] = datetime.now(timezone.utc).isoformat()
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    (args.output / 'REPORT.md').write_text(markdown(summary))
    audit = {'status': 'completed_offline_summary', 'passesFrozenGates': summary['passesFrozenGates'],
             'sources': source, 'summarySha256': sha(args.output / 'summary.json'),
             'reportSha256': sha(args.output / 'REPORT.md'), 'apiCalls': 0,
             'frozenCriteriaChanged': False, 'savedAggregationExactlyRecomputed': True}
    (args.output / 'receipt.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps({'passesFrozenGates': summary['passesFrozenGates'], 'failedGates': summary['failedGates'],
                      'publisherAiHits': summary['publisherAssignedAi'][AI], 'documentedNegativeAlerts': summary['documentedNegative'][AI],
                      'receipt': str(args.output / 'receipt.json')}))
    return 0 if summary['passesFrozenGates'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
