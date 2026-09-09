#!/usr/bin/env python3
"""Verify and summarize the fixed four paired origins without any API calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'eval/runs/sightengine-original-counterparts-v1'
spec = importlib.util.spec_from_file_location('four_counterpart', ROOT / 'scripts/eval-sightengine-original-counterparts.py')
study = importlib.util.module_from_spec(spec); spec.loader.exec_module(study)
manifest, helper, aggregator = study.validate()
receipt = study.read(RUN / 'receipt.json')
assert receipt['manifestSha256'] == study.sha(study.MANIFEST)
assert receipt['runnerSha256'] == study.sha(study.__file__)
assert len(receipt['results']) == 4
rows = []; total_operations = 0
for index, case in enumerate(manifest['cases']):
    result = receipt['results'][index]
    assert result['id'] == case['id']
    row = {'id': case['id'], 'sourceSha256': case['sha256'], 'generator': case['generator'],
           'parentId': case['groupId'], 'labelEvidenceStrength': case['labelEvidenceStrength'],
           'severeId': case['pairedSevere']['id'], 'severeSha256': case['pairedSevere']['sha256']}
    if result['status'] == 'not_attempted':
        rows.append({**row, 'originalStatus': 'not_attempted', 'originalDecision': 'technical_error'}); continue
    assert result == study.read(RUN / f'case-{index:02d}.json')
    assert result['mediaSha256'] == case['sha256'] and result['pairedSevere'] == case['pairedSevere']
    evidence = result['response'].get('evidence', {}); operations = evidence.get('request', {}).get('operations')
    if type(operations) is int: total_operations += operations
    assert total_operations == result['reportedOperationsObserved']
    complete = result['status'] == 'completed' and evidence.get('schemaValid') is True and evidence.get('coverageComplete') is True and type(operations) is int
    temporal = aggregator.aggregate_evidence(evidence.get('frames', []), duration_seconds=case['media']['durationSeconds'], technical_complete=complete, declared_interval_seconds=.5)
    assert temporal == result['temporal']
    old = case['pairedSevere']['savedTemporal']
    old_recomputed = aggregator.aggregate_evidence([{'positionSeconds': x['positionSeconds'], 'aiGenerated': x['aiGenerated']} for x in old['sampleRecords']],
        duration_seconds=case['pairedSevere']['media']['durationSeconds'], technical_complete=True, declared_interval_seconds=.5)
    assert old_recomputed == old
    original_scores = {x['positionSeconds']: x['aiGenerated'] for x in temporal['sampleRecords']}
    severe_scores = {x['positionSeconds']: x['aiGenerated'] for x in old['sampleRecords']}
    common = sorted(set(original_scores) & set(severe_scores))
    rows.append({**row, 'originalStatus': result['status'], 'originalDecision': temporal['verdict'] if complete else 'technical_error',
        'severeDecision': old['verdict'], 'originalPositiveSamples': sum(x['positive'] is True for x in temporal['sampleRecords']),
        'originalSamples': len(temporal['sampleRecords']), 'severePositiveSamples': sum(x['positive'] is True for x in old['sampleRecords']),
        'severeSamples': len(old['sampleRecords']), 'originalPersistentRuns': temporal['persistentRuns'], 'severePersistentRuns': old['persistentRuns'],
        'originalIsolatedAlerts': temporal['isolatedAlerts'], 'severeIsolatedAlerts': old['isolatedAlerts'],
        'pairedReportedPositions': [{'positionSeconds': t, 'originalScore': original_scores[t], 'severeScore': severe_scores[t]} for t in common],
        'unpairedOriginalPositions': sorted(set(original_scores)-set(severe_scores)), 'unpairedSeverePositions': sorted(set(severe_scores)-set(original_scores)),
        'elapsedSeconds': result['elapsedSeconds'], 'reportedOperations': operations})
assert total_operations == receipt['reportedOperationsObserved'] <= 240
summary = {'schemaVersion': 1, 'status': 'completed_offline_paired_diagnostic', 'createdAt': datetime.now(timezone.utc).isoformat(),
    'originalDetections': sum(row['originalDecision'] == 'persistent_ai_indicators' for row in rows),
    'severeDetections': sum(row.get('severeDecision') == 'persistent_ai_indicators' for row in rows), 'denominatorParents': 4,
    'errorsOrUnattempted': sum(row['originalDecision'] == 'technical_error' for row in rows), 'operations': total_operations,
    'degradationSensitiveParents': [row['parentId'] for row in rows if row['originalDecision'] == 'persistent_ai_indicators' and row.get('severeDecision') != 'persistent_ai_indicators'],
    'cases': rows, 'bothStagesExactlyRecomputed': True, 'frozenPolicyChanged': False, 'newAccuracyClaim': None,
    'limitations': manifest['analysis']['limitations'] + ['Reported timestamps are paired, not verified identical underlying decoded native frames.',
        'Original-versus-severe differences support sensitivity to the combined transform within these sources, not a general causal estimate of compression or motion effects.']}
study.save(RUN / 'paired-summary.json', summary)
lines = ['# Original versus severe: four-parent diagnostic', '',
    f'All **{summary["originalDetections"]}/4 originals** produced persistent AI indicators; their saved severe counterparts produced **{summary["severeDetections"]}/4**. '
    f'There were {summary["errorsOrUnattempted"]} errors/unattempted cases and {total_operations} reported operations. No retries or rule changes.', '',
    '| Publisher label | Original positive samples | Severe positive samples | Original verdict | Severe verdict |',
    '| --- | ---: | ---: | --- | --- |']
for row in rows:
    lines.append(f'| {row["generator"]} | {row.get("originalPositiveSamples",0)}/{row.get("originalSamples",0)} | {row.get("severePositiveSamples",0)}/{row.get("severeSamples",0)} | {row["originalDecision"]} | {row.get("severeDecision","unavailable")} |')
lines += ['', 'Vidu and Hailuo now provide within-parent evidence of sensitivity to the combined simulated-social transformation. '
    'The transform combines an85% crop, downscaling to360px,12fps resampling, a dark top overlay and H.264 CRF36 encoding. '
    'This does not isolate recompression or motion, establish that additional frame sampling would fix the loss, or recover a reliable negative classifier.', '',
    'The earlier standalone and fusion failures remain unchanged. These four original counterpart calls provide a mechanism diagnostic, not a new independent accuracy result or permission to retune the threshold.', '',
    'Exact media hashes, timestamp-paired scores, persistent/isolated alerts and recomputation checks are retained in paired-summary.json.', '',
    *['- '+text for text in summary['limitations']], '']
with (RUN / 'PAIRED_RESULTS.md').open('x') as handle: handle.write('\n'.join(lines))
study.save(RUN / 'paired-receipt.json', {'status': 'completed_offline_summary', 'apiCalls': 0,
    'inputReceiptSha256': study.sha(RUN / 'receipt.json'), 'manifestSha256': study.sha(study.MANIFEST),
    'freezeReceiptSha256': study.sha(study.PREP / 'receipt.json'), 'scriptSha256': study.sha(__file__),
    'summarySha256': study.sha(RUN / 'paired-summary.json'), 'reportSha256': study.sha(RUN / 'PAIRED_RESULTS.md')})
print(json.dumps({'originalDetections': summary['originalDetections'], 'severeDetections': summary['severeDetections'], 'parents':4, 'errorsOrUnattempted': summary['errorsOrUnattempted'], 'operations':total_operations,
    'samples': [{'generator': row['generator'], 'originalPositive':row.get('originalPositiveSamples'), 'severePositive':row.get('severePositiveSamples')} for row in rows]}))
