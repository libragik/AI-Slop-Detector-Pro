#!/usr/bin/env python3
"""Four fixed original counterparts; single-use, no retry, unchanged genai policy."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'eval/runs/sightengine-original-counterparts-v1'
PREP = ROOT / 'eval/runs/sightengine-original-counterparts-v1-freeze'
MANIFEST = ROOT / 'eval/fixtures/sightengine-original-counterparts-v1.json'
CLAIM = ROOT / 'eval/runs/sightengine-original-counterparts-v1-execution.json'
SOURCE = ROOT / 'eval/fixtures/sightengine-temporal-screen-v2.json'
SEVERE = ROOT / 'eval/runs/sightengine-temporal-screen-v2/receipt.json'
ORIGINALS = ROOT / 'eval/smoke-manifest.jsonl'
PINS = {
    'scripts/eval-sightengine-api.py': 'b953a1dd11f3f2b5bf81f3c9d7819466fed1d98c7defeb234e0439c82ca852be',
    'scripts/sightengine-temporal-evidence.py': '527b15281583255c975c60b7f8f3b44981c2a6744a6ab4af514bc61b667a7453',
    str(SOURCE.relative_to(ROOT)): '1374a18b17699d6aef0ef0868b21f9f580bdbaa667f26caa45d92d0dcacc25b7',
    str(SEVERE.relative_to(ROOT)): '4081f41523aafb1193dd06e52f48d83226fbf0985276c45355c78f5535c9fb34',
    str(ORIGINALS.relative_to(ROOT)): 'a73696821312e5e286d9b96906331129a36ed912f281389e0eae43cfb2c8909f',
}
IDS = ['503cbc93e819772076b46e86', '1f1759afdcf54d2091e65df7', '92d5b530d758407930843bc8', 'e4dd72c3ce6fe3ec4787f1b4']
POLICY = '6544a9d76ce994fecfc2c736b4f3af79b744f1cafa11a1e66145e849e30aea89'
ENV_KEYS = ('SIGHTENGINE_API_USER', 'SIGHTENGINE_API_SECRET')
CAP = 1048576

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def read(path): return json.loads(Path(path).read_bytes())
def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
def dependencies():
    for path, expected in PINS.items():
        if sha(ROOT / path) != expected: raise ValueError('Pinned source changed: ' + path)
    helper = module('scripts/eval-sightengine-api.py', 'counterpart_api')
    aggregate = module('scripts/sightengine-temporal-evidence.py', 'counterpart_policy')
    if aggregate.policy_configuration()[1] != POLICY: raise ValueError('Policy identity changed')
    return helper, aggregate
def save(path, value):
    # Reuse the already reviewed atomic/exclusive publication helper.
    helper = module('scripts/eval-sightengine-api.py', 'counterpart_write')
    helper.write_new(path, value)

def duplicate_audit(cases):
    targets = {c['sha256'] for c in cases}
    # Search content first; don't load every training/cache JSON file.
    command = ['rg', '-l', '-F', '-g', '*.json']
    for target in sorted(targets): command.extend(['-e', target])
    command.append(str(ROOT / 'eval/runs'))
    search = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if search.returncode not in (0, 1): raise ValueError('Duplicate audit search failed')
    files = [Path(path) for path in search.stdout.splitlines()]
    hits = []
    def inspect(value, path):
        if isinstance(value, dict):
            if value.get('mediaSha256') in targets and ('response' in value or ('sightengine' in str(path).lower() and path.name.startswith(('intent-', 'worker-')))):
                hits.append({'path': str(path.relative_to(ROOT)), 'sha256': value['mediaSha256'], 'kind': 'prior_submission_or_intent'})
            if value.get('provider') == 'sightengine' and value.get('sourceSha256') in targets and value.get('request', {}).get('submissionAttempted') is True:
                hits.append({'path': str(path.relative_to(ROOT)), 'sha256': value['sourceSha256'], 'kind': 'product_specialist_submission'})
            for child in value.values(): inspect(child, path)
        elif isinstance(value, list):
            for child in value: inspect(child, path)
    scanned = []
    for path in files:
        if path.is_relative_to(BASE) or path.is_relative_to(PREP): continue
        if path.stat().st_size > 50_000_000: raise ValueError('Oversized matching receipt cannot be silently excluded')
        data = read(path); inspect(data, path); scanned.append({'path': str(path.relative_to(ROOT)), 'sha256': sha(path)})
    return {'checkedAt': now(), 'targets': sorted(targets), 'matchingJsonFilesInspected': scanned, 'duplicateSubmissions': hits,
            'scope': 'Saved JSON receipts/intents under eval/runs; model-source mentions alone are not submission evidence. No provider-account history query.'}

def fixed_cases():
    source = read(SOURCE); prior = read(SEVERE)
    selected = [row for row in source['cases'] if row['cohort'] == 'publisher_assigned_ai' and row['quality'] == 'severe']
    original = {row['sha256']: row for row in map(json.loads, ORIGINALS.read_text().splitlines())}
    if len(selected) != 4: raise ValueError('Four severe source parents required')
    cases = []
    for index, derivative in enumerate(selected):
        item = original[derivative['originalParentSha256']]
        match = next(row for row in prior['results'] if row['id'] == derivative['id'])
        if match['mediaSha256'] != derivative['sha256'] or match['status'] != 'completed': raise ValueError('Missing exact severe result')
        cases.append({**item, 'order': index + 1, 'sourceLabel': 'ai', 'labelEvidenceStrength': 'publisher-assigned-benchmark',
                      'pairedSevere': {'id': derivative['id'], 'path': derivative['path'], 'sha256': derivative['sha256'], 'media': derivative['media'],
                                       'savedTemporal': match['temporal'], 'savedRequest': match['response']['evidence']['request']}})
    if [row['id'] for row in cases] != IDS: raise ValueError('Fixed selection order changed')
    return cases

def check_media(cases, probe=False):
    probes = []
    for case in cases:
        path = (ROOT / case['path']).resolve()
        if not path.is_relative_to(ROOT / 'eval/media') or sha(path) != case['sha256'] or path.stat().st_size != case['media']['bytes']:
            raise ValueError('Original media identity mismatch')
        if not 0 < case['media']['durationSeconds'] < 60 or not 0 < path.stat().st_size < 50_000_000:
            raise ValueError('Unsupported media size/duration')
        derivative = ROOT / case['pairedSevere']['path']
        if sha(derivative) != case['pairedSevere']['sha256']: raise ValueError('Severe media changed')
        if probe:
            result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries',
                'format=duration,size:stream=codec_type,width,height,avg_frame_rate', '-of', 'json', str(path)], capture_output=True, timeout=15, check=True)
            value = json.loads(result.stdout); video = [s for s in value['streams'] if s['codec_type'] == 'video']
            if len(video) != 1 or video[0]['width'] != case['media']['width'] or video[0]['height'] != case['media']['height'] or abs(float(value['format']['duration'])-case['media']['durationSeconds']) > .001:
                raise ValueError('Fresh media probe disagrees')
            probes.append({'id': case['id'], 'sha256': case['sha256'], 'probe': value})
    return probes

def prepare():
    helper, aggregate = dependencies(); cases = fixed_cases(); probes = check_media(cases, True)
    audit = duplicate_audit(cases)
    if audit['duplicateSubmissions']: raise ValueError('A counterpart already has a saved Sightengine submission')
    reserved = sum(helper.reservation(row) for row in cases)
    if reserved != 240: raise ValueError('Expected exactly240 reserved operations')
    manifest = {'schemaVersion': 1, 'id': 'sightengine-original-counterparts-v1', 'frozen': True, 'frozenAt': now(),
        'cases': cases, 'selection': 'All four publisher-labeled severe parents from the prior fixed25 screen, in its order; original counterparts only, including its two hits and two non-detections.',
        'api': {'endpoint': 'https://api.sightengine.com/1.0/video/check-sync.json', 'models': 'genai', 'intervalSeconds': .5},
        'policyFingerprint': POLICY, 'policyConfiguration': aggregate.policy_configuration()[0],
        'limits': {'requests': 4, 'reservedOperations': 240, 'maxOperations': 240, 'concurrency': 1, 'retries': 0, 'requestSeconds': 180, 'responseBytes': CAP},
        'analysis': {'primary': 'Apply unchanged temporal policy to originals and pair with saved severe outcomes. Report all four parents and full sampled-score sequences.',
            'hypothesis': 'Original-positive/severe-nondetection is evidence of sensitivity to the combined local social transformation; original-nondetection does not establish a compression-induced loss.',
            'noAdvanceOnPass': True, 'noThresholdFitting': True, 'errorsRetained': True,
            'limitations': ['Four publisher-labeled development parents, not independently authenticated origins or population accuracy.',
                'Severe transform combines crop, resize, frame rate, overlay and encoding; no individual-factor or motion-causality attribution.',
                'Prior negative failures remain failures; this AI-only diagnostic cannot establish specificity.',
                'Provider model version is not externally pinned; the calls and prior receipt are dated.',
                'No new Gemini, image-model or other-provider calls.']},
        'sources': [{'path': path, 'sha256': digest} for path, digest in PINS.items()],
        'runnerSha256': sha(__file__), 'labelsSentToProvider': False}
    PREP.mkdir(); save(MANIFEST, manifest); save(PREP / 'duplicate-audit.json', audit); save(PREP / 'media-probes.json', probes)
    sources = [*manifest['sources'], {'path': str(Path(__file__).relative_to(ROOT)), 'sha256': sha(__file__)}, {'path': str(MANIFEST.relative_to(ROOT)), 'sha256': sha(MANIFEST)}]
    for source in sources:
        target = PREP / 'source' / source['path']; target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as handle: handle.write((ROOT / source['path']).read_bytes())
    save(PREP / 'receipt.json', {'status': 'frozen_not_executed', 'createdAt': now(), 'sources': sources,
        'manifestSha256': sha(MANIFEST), 'duplicateAuditSha256': sha(PREP / 'duplicate-audit.json'),
        'mediaProbesSha256': sha(PREP / 'media-probes.json'), 'reservedOperations': reserved, 'apiCalls': 0,
        'requiresCoordinatedParentWindow': True})
    print(json.dumps({'status': 'ready_not_executed', 'manifestSha256': sha(MANIFEST), 'runnerSha256': sha(__file__), 'reservedOperations': reserved, 'duplicates': 0}))

def validate():
    helper, aggregate = dependencies(); manifest = read(MANIFEST); receipt = read(PREP / 'receipt.json')
    if sha(MANIFEST) != receipt['manifestSha256'] or manifest['runnerSha256'] != sha(__file__): raise ValueError('Frozen manifest/runner changed')
    if manifest['cases'] != fixed_cases() or manifest['policyFingerprint'] != POLICY or manifest['limits']['reservedOperations'] != 240:
        raise ValueError('Fixed inputs/policy changed')
    check_media(manifest['cases'])
    return manifest, helper, aggregate

def worker(index):
    manifest, helper, _ = validate(); case = manifest['cases'][index]
    plan = read(CLAIM); local = read(BASE / 'execution.json'); intent = read(BASE / f'intent-{index:02d}.json')
    if plan != local or plan['supervisorPid'] != os.getppid() or plan['manifestSha256'] != sha(MANIFEST) or intent['mediaSha256'] != case['sha256']:
        raise ValueError('Detached worker forbidden')
    credentials = tuple(os.environ.get(key, '') for key in ENV_KEYS)
    if not all(credentials): return {'kind': 'credentials_unavailable', 'operationsUnknown': False}
    wire = {**case, 'sourceLabel': 'unknown'}; body, content_type = helper.multipart(wire, credentials)
    save(BASE / f'worker-{index:02d}.json', {'startedAt': now(), 'mediaSha256': case['sha256']})
    connection = http.client.HTTPSConnection('api.sightengine.com', timeout=175, context=ssl.create_default_context())
    try:
        connection.request('POST', '/1.0/video/check-sync.json', body=body, headers={'Content-Type': content_type, 'Content-Length': str(len(body))})
        response = connection.getresponse()
        if response.status != 200: return {'kind': 'http_error', 'httpStatus': response.status, 'operationsUnknown': True}
        raw = response.read(CAP + 1)
        return {'kind': 'response', 'httpStatus': 200, 'evidence': helper.parse_response(raw, wire, credentials)}
    except Exception: return {'kind': 'transport_error', 'operationsUnknown': True}
    finally: connection.close()

def run(window):
    if window != 'parent-confirmed-no-concurrent-product-calls': raise ValueError('Coordinated window assertion required')
    manifest, helper, aggregate = validate()
    if not all(os.environ.get(key) for key in ENV_KEYS): raise ValueError('Missing credentials')
    audit = duplicate_audit(manifest['cases'])
    if audit['duplicateSubmissions']: raise ValueError('Duplicate counterpart submission detected before run')
    BASE.mkdir()
    plan = {'schemaVersion': 1, 'startedAt': now(), 'manifestSha256': sha(MANIFEST), 'freezeReceiptSha256': sha(PREP / 'receipt.json'),
        'runnerSha256': sha(__file__), 'output': str(BASE.relative_to(ROOT)), 'supervisorPid': os.getpid(),
        'coordinatedWindow': window, 'maximumRequests': 4, 'reservedOperations': 240, 'automaticRetries': 0}
    save(CLAIM, plan); save(BASE / 'execution.json', plan); save(BASE / 'duplicate-audit.json', audit)
    results = []; operations = 0; stop = None
    for index, case in enumerate(manifest['cases']):
        if stop:
            results.append({'id': case['id'], 'status': 'not_attempted', 'reason': stop}); continue
        if index: time.sleep(1)
        intent = {'index': index, 'id': case['id'], 'mediaSha256': case['sha256'], 'startedAt': now()}; save(BASE / f'intent-{index:02d}.json', intent)
        started = time.monotonic()
        try:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(index)], cwd=ROOT,
                capture_output=True, timeout=180, env={'PATH': os.environ.get('PATH', os.defpath), **{key: os.environ[key] for key in ENV_KEYS}})
            response = helper.load_json_bytes(process.stdout) if process.returncode == 0 and len(process.stdout) <= CAP else {'kind': 'worker_error', 'operationsUnknown': True}
        except subprocess.TimeoutExpired: response = {'kind': 'wall_timeout', 'operationsUnknown': True}
        except Exception: response = {'kind': 'worker_error', 'operationsUnknown': True}
        evidence = response.get('evidence', {}); reported = evidence.get('request', {}).get('operations')
        complete = response.get('kind') == 'response' and evidence.get('schemaValid') is True and evidence.get('coverageComplete') is True and type(reported) is int
        temporal = aggregate.aggregate_evidence(evidence.get('frames', []), duration_seconds=case['media']['durationSeconds'], technical_complete=complete, declared_interval_seconds=.5)
        if type(reported) is int: operations += reported
        if not complete or not temporal['technicalComplete'] or operations > 240:
            complete = False; stop = 'Technical completion or operation accounting failed; no remaining calls'
        result = {**intent, 'status': 'completed' if complete else 'stopped', 'elapsedSeconds': time.monotonic()-started,
            'response': response, 'temporal': temporal, 'reportedOperationsObserved': operations,
            'accountingMayBeIncomplete': not complete, 'pairedSevere': case['pairedSevere']}
        save(BASE / f'case-{index:02d}.json', result); results.append(result)
        print(json.dumps({'completed': index+1, 'total': 4, 'id': case['id'], 'status': result['status'], 'decision': temporal['verdict'], 'operations': operations}), flush=True)
    save(BASE / 'receipt.json', {**plan, 'completedAt': now(), 'status': 'stopped' if stop else 'completed', 'stopReason': stop,
        'results': results, 'reportedOperationsObserved': operations, 'accuracyClaim': None, 'analysisPurpose': manifest['analysis']})
    return 1 if stop else 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true'); parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--run-window'); parser.add_argument('--worker', type=int, choices=range(4)); args = parser.parse_args()
    try:
        if sum([args.prepare, args.validate_only, args.run_window is not None, args.worker is not None]) != 1: raise ValueError('Choose exactly one mode')
        if args.prepare: prepare()
        elif args.validate_only:
            validate(); print(json.dumps({'status': 'frozen_validation_passed', 'apiCalls': 0}))
        elif args.worker is not None: print(json.dumps(worker(args.worker), allow_nan=False))
        else: raise SystemExit(run(args.run_window))
    except Exception as error:
        # Local preparation failures contain no provider response or credential values.
        message = str(error) if args.prepare or args.validate_only else 'Counterpart diagnostic stopped; provider error text omitted.'
        print(message, file=sys.stderr); raise SystemExit(1)
