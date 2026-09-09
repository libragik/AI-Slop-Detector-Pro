#!/usr/bin/env python3
"""One-use, local-only manifest freeze. No inference, media edits, or network."""
import hashlib
import json
import math
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'eval/runs/sightengine-temporal-screen-v1-freeze'
PLAN = ROOT / 'eval/fixtures/sightengine-temporal-screen-v1.json'
POLICY = ROOT / 'eval/fixtures/sightengine-temporal-policy-v1.json'
if any(p.exists() for p in [OUT, PLAN, POLICY]):
    raise RuntimeError('This study is single-use; preserve existing evidence.')

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def read(path):
    return json.loads((ROOT / path).read_text())

def rows(path):
    return [json.loads(line) for line in (ROOT / path).read_text().splitlines() if line]

def ref(path):
    return {'path': path, 'sha256': sha(ROOT / path)}

def write_new(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')

stamp = datetime.now(timezone.utc).isoformat()
old_path = 'eval/fixtures/sightengine-api-diagnostic-v1.json'
old = read(old_path)
excluded = {c['sha256'] for c in old['cases']}
user_sha = '57be227b22cb166521cf698611886f6380c7f658a41217d03842395c63d270db'
excluded.add(user_sha)
smoke_path = 'eval/smoke-manifest.jsonl'
transformed_path = 'eval/transformed-manifest.jsonl'
negative_path = 'eval/runs/aegis-shots-v1-negative-build/manifest.jsonl'
source_plan_path = 'eval/fixtures/shot-study-source-plan.json'
generation_path = 'eval/fixtures/video-generation-receipt.json'
control_path = 'eval/control-manifest.jsonl'
source_plan = read(source_plan_path)
generators = ['luma', 'vidu', 'pika', 'gen4.5', 'hailuo2.3', 'pixverse_v5',
              'jimeng', 'kling2.5_turbo', 'seedance2.0', 'sora2', 'veo3.1', 'wan2.6']
originals = [r for r in rows(smoke_path) if r['generator'] in generators]
assert len(originals) == 12 and len({r['generator'] for r in originals}) == 12
originals.sort(key=lambda r: hashlib.sha256(('sightengine-temporal-v1-quality|' + r['sha256']).encode()).hexdigest())
transforms = rows(transformed_path)
quality_map = [('original', 'original'), ('mild', 'social_720p_crf28'),
               ('severe', 'repost_360p_crf36_12fps_crop')]
cases = []
for i, parent in enumerate(originals):
    quality, transform = quality_map[i % 3]
    candidates = [r for r in transforms if r['groupId'] == parent['groupId'] and r['transformation'] == transform and r['split'] == 'development']
    assert len(candidates) == 1
    r = candidates[0]
    cases.append({
        'id': r['id'], 'path': r['path'], 'sha256': r['sha256'],
        'cohort': 'publisher_assigned_ai', 'sourceLabel': 'ai',
        'expectedPrimaryDecision': 'ai', 'labelEvidenceStrength': 'publisher-assigned-benchmark',
        'generator': r['generator'], 'quality': quality, 'parentGroups': [r['groupId']],
        'primaryParentId': r['groupId'], 'sourceUrl': r['sourceUrl'], 'license': r['license'],
        'groundTruth': r['groundTruth'], 'originalParentSha256': parent['sha256'],
        'sourceManifest': ref(transformed_path), 'sourceSelectionManifest': ref(smoke_path),
        'media': r['media'], 'registeredAncestryOverlapWithFiveControls': False,
        'limitations': 'Publisher-assigned origin; no per-clip generation job or authenticated origin. Previously consumed development source. Proprietary vendor training overlap and semantic cross-source overlap unknown.'})

negative_cases = ['NASA/base/master', 'NASA/base/severe', 'NOAA/base/mild', 'NOAA/base/severe',
                  'USGS/base/master', 'USGS/base/severe', 'pendulum/base/master', 'pendulum/base/severe',
                  'rolling/base/master', 'rolling/base/severe']
negative_rows = rows(negative_path)
for case_id in negative_cases:
    r = next(r for r in negative_rows if r['caseId'] == case_id)
    parent = source_plan['parents'][r['parentId']]
    evidence = [ref(source_plan_path), ref(parent['originReceiptPath']),
                ref(r['constructionReceiptPath']), ref(r['frameLineagePath'])]
    assert evidence[1]['sha256'] == parent['originReceiptSha256']
    assert evidence[2]['sha256'] == r['constructionReceiptSha256']
    assert evidence[3]['sha256'] == r['frameLineageSha256']
    if r['label'] == 'camera':
        evidence += [ref('eval/sources/camera-control-inspection.json'), ref('eval/CAMERA_CONTROL_INSPECTION.md')]
        record = next(x for x in read(parent['originReceiptPath'])['records'] if x['sha256'] == parent['sha256'])
        source_url = record['url']
        truth = 'Agency-documented dated camera event, locally inspected selected interval, source hash and deterministic derivative/frame lineage retained. Camera-origin imagery includes conventional processing.'
        strength = 'documented-camera-source'
    else:
        source_url = 'https://www.blender.org/'
        truth = 'Conventional Blender render from preserved code and render receipt; no generative pixel model. Assistant-authored scene code is disclosed and is outside the generative-visual label.'
        strength = 'conventional-render-receipt'
    cases.append({
        'id': r['id'], 'sourceCaseId': case_id, 'path': r['path'], 'sha256': r['sha256'],
        'cohort': 'documented_negative', 'sourceLabel': r['label'],
        'expectedPrimaryDecision': 'no_clear_indicators', 'labelEvidenceStrength': strength,
        'generator': 'none', 'quality': r['quality'], 'parentGroups': [r['parentId']],
        'primaryParentId': r['parentId'], 'sourceUrl': source_url,
        'sourceManifest': ref(negative_path), 'groundTruth': {'basis': truth, 'sourceParent': parent},
        'evidence': evidence, 'media': r['media'],
        'registeredAncestryOverlapWithFiveControls': r['parentId'] in ['NOAA', 'pendulum'],
        'limitations': 'Previously consumed development family, not independent validation. Agency footage is not an authenticated pristine master; NASA and USGS are timelapses. Trims and qualities remain grouped.'})

for r in rows(control_path):
    if r['label'] != 'cgi' or r['transformation'] not in ['conventional-cgi-30', 'conventional-cgi-42']:
        continue
    cases.append({
        'id': r['id'], 'path': r['path'], 'sha256': r['sha256'],
        'cohort': 'documented_negative', 'sourceLabel': 'cgi',
        'expectedPrimaryDecision': 'no_clear_indicators', 'labelEvidenceStrength': 'documented-pre-generative-cgi-production',
        'generator': 'none', 'quality': 'master', 'parentGroups': ['sintel-2010'],
        'primaryParentId': 'sintel-2010', 'sourceUrl': r['sourceUrl'], 'license': r['license'],
        'groundTruth': {'basis': r['groundTruth'], 'sourceIntervalSeconds': [30,36] if r['transformation'].endswith('-30') else [42,48]},
        'sourceManifest': ref(control_path), 'evidence': [ref('scripts/build-controls.py'), ref('eval/fixtures/generated-control-build-receipt.json')],
        'media': r['media'], 'registeredAncestryOverlapWithFiveControls': True,
        'limitations': 'Two new byte/interval checks from the same Sintel production previously tested. Not two independent CGI productions. Existing build script/manifest and acquired source hash are retained.'})

generation = read(generation_path)
d = generation['download']
cases.append({
    'id': 'veo-receipted-raw-same-parent', 'path': d['path'], 'sha256': d['sha256'],
    'cohort': 'receipt_backed_same_parent_check', 'sourceLabel': 'ai',
    'expectedPrimaryDecision': 'ai', 'labelEvidenceStrength': 'direct-generation-receipt',
    'generator': generation['request']['model'], 'quality': 'original_with_audio',
    'parentGroups': ['generated-operation:' + generation['operationName']],
    'primaryParentId': 'generated-operation:' + generation['operationName'],
    'sourceUrl': 'https://ai.google.dev/gemini-api/docs/veo',
    'groundTruth': {'basis': 'One direct text-only provider generation operation; no reference media supplied.',
                    'inputMedia': generation['inputMedia'], 'operationName': generation['operationName'],
                    'aiIntervalSeconds': [0,8]},
    'evidence': [ref(generation_path), ref('eval/GENERATED_ORIGIN_CONTROL.md')],
    'registeredAncestryOverlapWithFiveControls': True,
    'limitations': 'Same generated visual parent as the consumed silent five-control clip; raw output includes audio. Visual-only genai request supplies no source claims or audio labels. This is a same-parent consistency check, not unseen generation.'})
assert len(cases) == 25
assert Counter(c['cohort'] for c in cases) == {'publisher_assigned_ai':12,'documented_negative':12,'receipt_backed_same_parent_check':1}
assert Counter(c['quality'] for c in cases if c['cohort']=='publisher_assigned_ai') == {'original':4,'mild':4,'severe':4}
assert len({c['sha256'] for c in cases}) == 25 and not ({c['sha256'] for c in cases} & excluded)

for c in cases:
    p = ROOT / c['path']
    assert sha(p) == c['sha256'], c['path']
    raw = subprocess.check_output(['ffprobe','-v','error','-protocol_whitelist','file,pipe',
        '-show_format','-show_streams','-of','json',str(p)], timeout=20)
    probe = json.loads(raw)
    v = next(x for x in probe['streams'] if x['codec_type'] == 'video')
    duration = float(probe['format']['duration'])
    if 'media' in c:
        assert abs(duration - c['media']['durationSeconds']) < 0.03
    c['media'] = {'bytes': p.stat().st_size, 'durationSeconds': duration,
                  'width':v['width'],'height':v['height'],'frameRate':v['avg_frame_rate'],
                  'hasAudio':any(x['codec_type']=='audio' for x in probe['streams'])}
    assert 0 < duration < 60 and c['media']['bytes'] < 50_000_000
    c['mediaProbeSha256'] = hashlib.sha256(raw).hexdigest()
    c['reservedOperations'] = 5 * (math.ceil(duration / 0.5) + 1)
    c['_probe'] = probe

policy = {
    'schemaVersion':1,'id':'sightengine-temporal-policy-v1','frozen':True,'frozenAt':stamp,
    'api':{'endpoint':'https://api.sightengine.com/1.0/video/check-sync.json','models':'genai','intervalSeconds':0.5,'positionUnit':'milliseconds'},
    'threshold':0.5,'minimumConsecutivePositiveSamples':2,'maximumConsecutiveGapSeconds':0.6,
    'positiveDefinition':'finite ai_generated score >=0.5',
    'consecutiveDefinition':'Adjacent elements in the complete, strictly time-ordered returned frame list; every element in the run positive and every time gap <=0.6 seconds. Never skip an intervening negative sample.',
    'decisions':{'ai':'At least one qualifying run of two or more positive returned samples.',
                 'inconclusive':'One or more positive samples but no qualifying run, including multiple separated isolated positives.',
                 'no_clear_indicators':'Zero positive samples with complete validated reported sampling coverage; not proof of non-generative origin.',
                 'error':'Any request, schema, accounting, timestamp or coverage failure; no partial-result salvage.'},
    'coverage':{'firstFrameMaxSeconds':0.1,'maxGapSeconds':0.6,'tailGapSeconds':0.6,
                'required':'Finite distinct ordered timestamps in [0,duration); finite scores in [0,1]; complete reported sampling required for every decision.'},
    'prohibited':['No threshold/run-length/quality-specific tuning','No Gemini or style override','No captions, source labels or provenance metadata in classifier request','No retries of uncertain submissions','No inference that consecutive errors are independent'],
    'limitations':['Sampled temporal corroboration is not physical proof of origin.','Brief subsecond inserts can yield one or zero hits and be Inconclusive or missed. No subsecond sensitivity claim.','Scores remain uncalibrated; no population accuracy claim.','Vendor model version is not immutably pinned; retain date and returned model/request identifiers.']}
policy_bytes = (json.dumps(policy,indent=2,ensure_ascii=False)+'\n').encode()
candidate_sha = hashlib.sha256(policy_bytes).hexdigest()
cases.sort(key=lambda c: hashlib.sha256(('sightengine-temporal-v1-order|'+c['sha256']).encode()).hexdigest())
for i,c in enumerate(cases,1):
    c['order'] = i
reserve = sum(c['reservedOperations'] for c in cases)
assert reserve <= 3000
plan = {
    'schemaVersion':1,'id':'sightengine-temporal-screen-v1','frozen':True,'frozenAt':stamp,
    'purpose':'Prospective narrow rejection screen for a new temporal rule. All media preexists; no model result used for selection. No product integration or validation claim.',
    'candidate':{'path':str(POLICY.relative_to(ROOT)),'sha256':candidate_sha},
    'sourceFailedStudy':ref(old_path),
    'exclusions':{'submittedFiveSha256s':[c['sha256'] for c in old['cases']], 'userReelSha256':user_sha,
                  'userReelPath':'eval/media/user-reel-Da7nZ5hs6H7/'+user_sha+'.mp4','comparison':'Exact bytes excluded; shared parent ancestry explicitly disclosed.'},
    'selection':{'generators':generators,'positiveQualityAssignment':'Sort original parents by SHA256(sightengine-temporal-v1-quality|originalSHA), cycle original/mild/severe, four per quality.',
                 'negativeCaseIds':negative_cases+['conventional-cgi-30','conventional-cgi-42'],
                 'selectionUsedModelScores':False,'sameParentCheck':'Raw original receipted Veo; scored separately.'},
    'limits':{'requests':25,'operations':3000,'reservedOperations':reserve,'responseBytes':1048576,
              'requestSeconds':180,'minimumStartIntervalSeconds':1,'concurrency':1,'mediaBytesPerFile':50000000},
    'advancementCriteria':{
        'technical':'All25 cases complete with valid schema, coverage, accounting and exact outgoing bytes; any error, unattempted case or operational stop fails advancement.',
        'documentedNegative':'Zero AI alerts among12 files and six parent groups; at least10/12 files and5/6 parents must be no_clear_indicators rather than Inconclusive.',
        'publisherAssignedAi':'At least10/12 AI alerts overall and at least3/4 in each assigned quality. Inconclusive/no_clear_indicators/error count as non-detections; publisher-assigned recall is reported separately.',
        'receiptBackedSameParent':'Raw Veo must be AI; report1/1 or0/1 separately with shared-parent qualification.',
        'scope':'A pass only supports considering narrow experimental integration or a separately frozen next test; no calibrated/population/independent or subsecond/mixed-positive validation claim.',
        'classificationFailure':'Finish remaining frozen cases if operational safeguards remain valid. Preserve failure; no score-aware replacement, threshold rescue or rerun.'},
    'reporting':{'parentRule':'Within each primaryParentId, any AI result => alert; else any Inconclusive => inconclusive; else all no_clear_indicators => clear. Any processing error separately fails the parent.',
                 'required':['Per-file and per-parent decisions','Publisher-assigned recall overall and byquality, including everyabstention/non-detection','Documentednegative falsealerts and usablecoverage byfile andparent','Same-parent receiptcheck separate','Allisolatedpositive samples and qualifyingruns withtimestamps/rawscores','Allerrors/unattemptedcases/operations/latency','Uncertaintyifreportedmustrespectdependentderivatives andlimitedcuratedsources'],
                 'parentCounts':{'publisherAssignedAi':12,'documentedNegative':6,'receiptBackedSameParent':1},
                 'missingCoverage':['No eligible verified new mixed-positive clip after byteexclusions.','One receipted generatedparent alreadyconsumed; no new independentgeneratedsource.','No new actualInstagramroundtrip or userReel call.']},
    'cases':cases}
OUT.mkdir(parents=True)
for c in cases:
    probe = c.pop('_probe')
    write_new(OUT / 'probes' / (c['id']+'.json'),probe)
write_new(POLICY,policy)
assert sha(POLICY)==candidate_sha
write_new(PLAN,plan)
references = {x['path']:x for c in cases for x in c.get('evidence',[])}
for path in [old_path,smoke_path,transformed_path,negative_path,source_plan_path,control_path,generation_path,str(Path(__file__).relative_to(ROOT))]:
    references[path]=ref(path)
for item in references.values():
    target = OUT/'source'/item['path']
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes((ROOT/item['path']).read_bytes())
    assert sha(target)==item['sha256']
for path in [PLAN,POLICY]:
    (OUT/path.name).write_bytes(path.read_bytes())
receipt={'schemaVersion':1,'status':'frozen_prepared_not_executed','preparedAt':stamp,
         'candidateSha256':candidate_sha,'manifest':ref(str(PLAN.relative_to(ROOT))),
         'preparationScript':ref(str(Path(__file__).relative_to(ROOT))),
         'sourceReferences':list(references.values()),'cases':25,'reservedOperations':reserve,'operationCap':3000,
         'assertions':{'allMediaHashesMatched':True,'allMediaDurationsFreshlyProbed':True,'all25Unique':True,
                       'fiveConsumedAndUserBytesExcluded':True,'fourAiPerQuality':True,'zeroModelCalls':True,
                       'zeroNetworkRequests':True,'zeroMediaEdits':True,'zeroSecretReads':True}}
write_new(OUT/'receipt.json',receipt)
print(json.dumps({'manifest':receipt['manifest'],'candidateSha256':candidate_sha,
                  'receiptSha256':sha(OUT/'receipt.json'),'cases':25,'reservedOperations':reserve,'operationCap':3000}))
