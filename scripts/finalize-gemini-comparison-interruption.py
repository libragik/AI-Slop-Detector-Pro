#!/usr/bin/env python3
"""One-use accounting after the parent-authorized interruption; no provider calls."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'eval/runs/sightengine-temporal-screen-v2-gemini-comparison'
def read(path): return json.loads(path.read_bytes())
def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2)
        handle.write('\n')
def time(value): return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))

plan = read(OUT / 'execution.json')
interruption = read(OUT / 'external-interruption-intent.json')
manifest = read(OUT / 'manifest.json')
assert len(manifest['cases']) == 25 and interruption['returnedCaseCount'] == 24
assert interruption['pendingElapsedSeconds'] >= 300
remaining = subprocess.run(['ps', '-p', str(interruption['pid']), '-o', 'pid='], capture_output=True, text=True)
assert not remaining.stdout.strip(), 'The owned process has not terminated'
assert hashlib.sha256((OUT / 'adapter.mjs').read_bytes()).hexdigest() == plan['adapter']['sha256']
results = []
for index, item in enumerate(manifest['cases']):
    prefix = f'{index+1:02d}-{item["id"]}'
    path = OUT / f'{prefix}.json'
    if path.exists():
        row = read(path)
        assert row['status'] == 'completed'
    else:
        assert item['id'] == interruption['pendingId']
        intent = read(OUT / f'{prefix}.intent.json')
        row = {**{key: intent[key] for key in ['index', 'id', 'mediaSha256', 'startedAt']},
               'completedAt': interruption['at'], 'elapsedMs': round(interruption['pendingElapsedSeconds'] * 1000),
               'status': 'failed', 'externallyInterrupted': True,
               'error': {'category': 'ExternalInterruptionAfterUnboundedWait', 'rawErrorOmitted': True},
               'providerOutcome': 'unknown', 'providerStage': 'undetermined',
               'providerBilling': 'unknown', 'remoteFileCleanup': 'unconfirmed after process termination',
               'usageAccountingIncomplete': True, 'result': None}
        save(path, row)
    assert row['index'] == index and row['mediaSha256'] == item['sha256']
    results.append(row)
completed = [row for row in results if row['status'] == 'completed']
assert len(completed) == 24 and sum(row.get('externallyInterrupted') is True for row in results) == 1
source = Path(__file__)
receipt = {**plan, 'status': 'externally_interrupted_with_partial_results',
    'completedAt': interruption['at'], 'elapsedMs': round((time(interruption['at']) - time(plan['startedAt'])).total_seconds() * 1000),
    'stopReason': 'Parent-authorized SIGTERM after the sole pending clip exceeded300seconds',
    'processExitCode': 143, 'counts': {'completed': 24, 'failed': 1, 'unattempted': 0},
    'externalInterruption': {**interruption, 'processTerminationObserved': True, 'exitCodeObservedViaPty': 143},
    'finalizedExternally': {'path': str(source.relative_to(ROOT)), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                          'apiCalls': 0, 'immutableInputsChanged': False, 'returnedResultsRewritten': False},
    'usage': {**{key: sum(row['usage'][key] for row in completed) for key in ['inputTokensObserved', 'outputTokensObserved', 'failedPasses', 'missingUsagePasses']},
              'accountingMayBeIncomplete': True, 'interruptedCasesWithUnknownUsage': 1,
              'note': 'Returned pass usage only; failed adjudication, internal retries and externally interrupted request billing may not be exposed.'},
    'results': results}
save(OUT / 'receipt.json', receipt)
with (OUT / source.name).open('xb') as handle: handle.write(source.read_bytes())
print(json.dumps({key: receipt[key] for key in ['status', 'processExitCode', 'counts', 'usage', 'elapsedMs']}))
