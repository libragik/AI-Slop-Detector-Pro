#!/usr/bin/env python3
"""Separate, frozen shot/window AEGIS study; never reopens the old screen."""
import argparse
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'scripts/eval-aegis.py'
BASE_SHA = '1390d13e5b54f0122316e672a0c0456f2602ee02ec68ada328dd3b1d50578838'
WEIGHTS = ROOT / 'eval/models/aegis/model.safetensors'
WEIGHTS_SHA = 'c464af41b7528f18c1a3de748dde4dc5171aafaf8469c8848036ac45329ae474'
PROTOCOL = ROOT / 'eval/AEGIS_SHOT_EVALUATION_PROTOCOL.md'
GENERATION_PLAN = ROOT / 'eval/fixtures/shot-study-generation-plan.json'
SOURCE_PLAN = ROOT / 'eval/fixtures/shot-study-source-plan.json'
VENDOR_RECEIPT = ROOT / 'eval/sources/aegis-vendor-manifest.json'
VENDOR_RECEIPT_SHA = '53d109195b6d134de2b2d1f39c01122d3992d32c602ff6d4c644bc8b5875fcbe'
CONVERSION_RECEIPT = ROOT / 'eval/sources/aegis-safe-conversion-receipt.json'
CONVERSION_RECEIPT_SHA = '6291fcea81af08892c6646bd5bb6f6e969de6fa7a2bf68722250b0faef7141e9'
STAGES = {'negative-45': 45, 'veo-30': 30, 'wan-30': 30}
CASE_FIELDS = ('label', 'parentId', 'hostId', 'donorId', 'composition', 'quality', 'stage', 'ancestors')
MAX_WINDOWS = 32
VIDEO_TIMEOUT = 120
MAX_RSS = 8 * 1024**3


def fixed_policy():
    return {'study': 'aegis-shots-v1', 'modelSha256': WEIGHTS_SHA,
            'device': 'cpu', 'dtype': 'float32', 'threads': 4, 'batchSize': 1,
            'sceneThreshold': 10, 'sceneDecision': 'lavfi.scd.time marker',
            'maxWindowSeconds': 4, 'strideSeconds': 2, 'tailAligned': True,
            'framesPerWindow': 16, 'threshold': 0.5, 'comparator': '>=',
            'head': 'main-fused', 'aggregation': 'any-positive', 'seed': 20260905,
            'scoreIsProbability': False, 'maxWindowsPerVideo': MAX_WINDOWS,
            'maxShotsPerVideo': 128, 'timeoutSecondsPerVideo': VIDEO_TIMEOUT,
            'maxRssBytes': MAX_RSS, 'resourceGuardPollSeconds': 0.1,
            'opencvThreadsRequested': 0, 'opencvThreadsReported': 1,
            'opencvParallelFramework': 'GCD'}


def common_sources():
    return [(Path(__file__), 'eval-aegis-shots.py'), (BASE, 'aegis-base.py'),
            (PROTOCOL, 'protocol.md'), (GENERATION_PLAN, 'generation-plan.json'),
            (SOURCE_PLAN, 'source-plan.json'), (VENDOR_RECEIPT, 'vendor-manifest.json'),
            (CONVERSION_RECEIPT, 'weight-conversion-receipt.json'),
            (ROOT / 'scripts/build-shot-study.py', 'build-shot-study.py'),
            (ROOT / 'scripts/ffmpeg-fps-lineage.py', 'ffmpeg-fps-lineage.py')]


def expected_source_entries():
    if (sha(BASE) != BASE_SHA or sha(VENDOR_RECEIPT) != VENDOR_RECEIPT_SHA
            or sha(CONVERSION_RECEIPT) != CONVERSION_RECEIPT_SHA):
        raise ValueError('Pinned base/vendor/weight-conversion contract changed')
    entries = [{'path': name, 'sha256': sha(path)} for path, name in common_sources()]
    vendor = json.loads(VENDOR_RECEIPT.read_text())
    for name, expected in vendor['files'].items():
        if sha(ROOT / 'eval/vendor/aegis' / name) != expected['sha256']:
            raise ValueError('Pinned vendor model computation changed')
        entries.append({'path': 'vendor/' + name, 'sha256': expected['sha256']})
    return entries


def local_path(value):
    """Evidence paths must resolve inside this workspace, including symlinks."""
    if not isinstance(value, str) or not value:
        raise ValueError('Missing evidence path')
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError('Evidence path escaped the workspace')
    return path


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_score(value):
    if not isinstance(value, dict) or value.get('status') != 'ok':
        return False
    score, logit = value.get('syntheticScore'), value.get('fusedLogit')
    return (finite_number(score) and finite_number(logit) and 0 <= score <= 1
            and abs(score - 1 / (1 + math.exp(-max(-700, min(700, logit))))) <= 1e-5)


def read_lineage(row, plan=None):
    path = local_path(row['frameLineagePath'])
    if sha(path) != row['frameLineageSha256']:
        raise ValueError('Construction frame lineage changed')
    frames = json.loads(path.read_text())
    count = 60 if row['quality'] == 'severe' else 120
    plan = json.loads(SOURCE_PLAN.read_text()) if plan is None else plan
    fields = {'outputIndex', 'masterIndex', 'hostParentId', 'hostSourceFrame',
              'donorParentId', 'donorSourceFrame', 'donorAlpha', 'knownAiContribution'}
    if not isinstance(frames, list) or len(frames) != count:
        raise ValueError('Construction lineage does not cover every decoded frame')
    previous = -1
    for i, frame in enumerate(frames):
        if not isinstance(frame, dict) or set(frame) != fields:
            raise ValueError('Unknown construction lineage schema')
        master = frame['masterIndex']
        if (type(master) is not int or not 0 <= master < 120 or master <= previous
                or frame['outputIndex'] != i or type(frame['outputIndex']) is not int
                or (row['quality'] != 'severe' and master != i)
                or frame['hostParentId'] != row['hostId'] or frame['donorParentId'] != row['donorId']
                or type(frame['hostSourceFrame']) is not int or frame['hostSourceFrame'] < 0):
            raise ValueError('Construction lineage identity/index differs from the frozen case')
        previous = master
        alpha = 0.0
        if row['composition'] in ('hardcut', 'blend') and 36 <= master < 84:
            k = master - 36
            alpha = 1.0 if row['composition'] == 'hardcut' else min(1, (2*k+1)/12, (95-2*k)/12)
        if not finite_number(frame['donorAlpha']) or abs(frame['donorAlpha'] - alpha) > 1e-7:
            raise ValueError('Construction donor alpha differs from the frozen edit')
        if ((alpha == 0 and frame['donorSourceFrame'] is not None)
                or (alpha > 0 and (type(frame['donorSourceFrame']) is not int or frame['donorSourceFrame'] < 0))):
            raise ValueError('Construction donor source-frame presence is inconsistent')
        host_ai = plan['parents'][row['hostId']]['label'] == 'ai'
        donor_ai = row['donorId'] is not None and plan['parents'][row['donorId']]['label'] == 'ai'
        expected_ai = int(host_ai) * (1-alpha) + int(donor_ai) * alpha
        if (not finite_number(frame['knownAiContribution'])
                or abs(frame['knownAiContribution'] - expected_ai) > 1e-7):
            raise ValueError('Construction AI contribution differs from frozen origin labels')
    return frames


def window_lineage(window, frames):
    selected = [frames[i] for i in window['requestedFrameIndices']]
    return {'sampledFrameLineage': selected,
            'sampledDonorFrames': sum(frame['donorAlpha'] > 0 for frame in selected),
            'sampledFullyDonorFrames': sum(frame['donorAlpha'] == 1 for frame in selected),
            'sampledBlendEdgeFrames': sum(0 < frame['donorAlpha'] < 1 for frame in selected),
            'sampledKnownAiFrames': sum(frame['knownAiContribution'] > 0 for frame in selected),
            'sampledFullyAiFrames': sum(frame['knownAiContribution'] == 1 for frame in selected)}


def validate_manifest(manifest, stage, plan, build_receipt_path):
    """A self-consistent arbitrary manifest is not a registered source selection."""
    rows = read_rows(manifest)
    if (len(rows) != STAGES[stage] or len({row['id'] for row in rows}) != len(rows)
            or len({row['path'] for row in rows}) != len(rows)):
        raise ValueError('Complete exact stage manifest required')
    ids = plan['stages'][stage]['caseIds']
    if len(ids) != STAGES[stage] or len(set(ids)) != len(ids):
        raise ValueError('Invalid frozen stage case denominator')
    if len({row['caseId'] for row in rows}) != len(rows) or {row['caseId'] for row in rows} != set(ids):
        raise ValueError('Manifest case selection differs from frozen source plan')
    if [row['caseId'] for row in rows] != ids:
        raise ValueError('Manifest order differs from the frozen stage order')
    for row in rows:
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', row['id'])
                or row.get('stage') != stage or row.get('split') != 'development'
                or row.get('dataset') != 'fresh-origin-shot-study'):
            raise ValueError('Only safe, separately registered fresh stage identities may run')
        case = plan['cases'][row['caseId']]
        if any(field not in row or field not in case or row[field] != case[field] for field in CASE_FIELDS):
            raise ValueError('Manifest source/label/edit/quality differs from frozen case')
        if row['label'] not in ('ai', 'mixed', 'camera', 'cgi', 'nongenerative_mixed'):
            raise ValueError('Unrecognized frozen ground-truth label')
        if (not isinstance(row['ancestors'], list) or not row['ancestors']
                or len(set(row['ancestors'])) != len(row['ancestors'])):
            raise ValueError('Missing or repeated source ancestry')
        media = local_path(row['path'])
        if media.stat().st_size > 50_000_000 or sha(media) != row['sha256']:
            raise ValueError('Manifest media bytes differ from registered build output')
        read_lineage(row, plan)
    build = json.loads(Path(build_receipt_path).read_text())
    required_hashes = {'manifestSha256': sha(manifest), 'builderSha256': sha(ROOT / 'scripts/build-shot-study.py'),
                       'sourcePlanSha256': sha(SOURCE_PLAN), 'generationPlanSha256': sha(GENERATION_PLAN),
                       'evaluationProtocolSha256': sha(PROTOCOL)}
    if any(build.get(key) != value for key, value in required_hashes.items()):
        raise ValueError('Build receipt changed or used another frozen plan/builder')
    if (build.get('status') != 'completed' or build.get('stage') != stage
            or build.get('completed') != len(rows) or build.get('parentFilesUnchanged') is not True
            or build.get('detectorCalls') != 0):
        raise ValueError('Construction stage is incomplete, failed or already used a detector')
    common_sources = {str(path.relative_to(ROOT)) for path in
                      (ROOT / 'scripts/build-shot-study.py', ROOT / 'scripts/ffmpeg-fps-lineage.py',
                       SOURCE_PLAN, GENERATION_PLAN, PROTOCOL)}
    source_files = build.get('sourceFiles', [])
    if len(source_files) != len(common_sources) or {item['path'] for item in source_files} != common_sources:
        raise ValueError('Construction receipt lacks its complete frozen source snapshots')
    for item in source_files:
        if sha(local_path(item['path'])) != item['sha256'] or sha(local_path(item['snapshot'])) != item['sha256']:
            raise ValueError('Construction source or its immutable snapshot changed')
    if local_path(build.get('manifestPath')) != Path(manifest).resolve():
        raise ValueError('Build receipt points to another stage manifest')
    outputs = build.get('outputs')
    if not isinstance(outputs, list) or len(outputs) != len(rows):
        raise ValueError('Build receipt does not retain every exact manifest row')
    if sorted(outputs, key=lambda row: row['caseId']) != sorted(rows, key=lambda row: row['caseId']):
        raise ValueError('Manifest rows differ from complete construction receipt')
    parents = build.get('parentReceipts')
    ancestors = set(parent for row in rows for parent in row['ancestors'])
    if (not isinstance(parents, list) or len(parents) != len(ancestors)
            or {parent['parentId'] for parent in parents} != ancestors):
        raise ValueError('Build receipt is missing or duplicates an ancestral parent')
    for parent in parents:
        if sha(local_path(parent['path'])) != parent['sha256']:
            raise ValueError('An original parent changed after construction')
        origin = local_path(parent['originReceiptPath'])
        if sha(origin) != parent['originReceiptSha256']:
            raise ValueError('An original origin receipt changed after construction')
        registered = plan.get('parents', {}).get(parent['parentId'])
        if not isinstance(registered, dict):
            raise ValueError('An ancestor lacks its frozen source-plan binding')
        if 'generationSlot' not in registered:
            if any(registered.get(key) != parent.get(key) for key in
                   ('path', 'sha256', 'originReceiptPath', 'originReceiptSha256')):
                raise ValueError('Original parent differs from frozen source identity')
        else:
            # Generated bytes do not exist at Stage 1; their exact slot, request and
            # subsequent output identity must be established by a hashed receipt.
            origin_data = json.loads(origin.read_text())
            slot = registered['generationSlot']
            if (slot != parent['parentId'] or origin_data.get('generationSlot') != slot
                    or origin_data.get('generationPlanSha256') != sha(GENERATION_PLAN)
                    or origin_data.get('evaluationProtocolSha256') != sha(PROTOCOL)
                    or origin_data.get('output') != {'path': parent['path'], 'sha256': parent['sha256']}
                    or origin_data.get('inputMedia') != []
                    or origin_data.get('status') != 'completed'):
                raise ValueError('Generated parent lacks verified frozen-slot output provenance')
            raw_ref = origin_data['rawGenerationReceipt']
            raw_path = local_path(raw_ref['path'])
            if sha(raw_path) != raw_ref['sha256']:
                raise ValueError('Raw generator receipt changed')
            raw = json.loads(raw_path.read_text())
            generation = json.loads(GENERATION_PLAN.read_text())
            if (raw.get('status') != 'succeeded' or raw.get('generationSlot') != slot
                    or raw.get('generationPlanSha256') != sha(GENERATION_PLAN)
                    or raw.get('evaluationProtocolSha256') != sha(PROTOCOL)
                    or raw.get('output') != origin_data['output']):
                raise ValueError('Raw generator receipt disagrees with frozen parent output')
            if slot.startswith('V'):
                request = next(run['request'] for run in generation['veoRuns'] if run['id'] == slot)
                response = raw.get('operation', {}).get('response', {})
                filtered = response.get('raiMediaFilteredCount', 0)
                if (raw.get('request') != request or raw.get('inputMedia') != []
                        or raw.get('operation', {}).get('done') is not True
                        or raw.get('operation', {}).get('error')
                        or raw.get('scriptSha256') != generation['veoScriptSha256']
                        or not isinstance(response.get('generatedVideos'), list)
                        or len(response['generatedVideos']) != 1
                        or type(filtered) is not int or filtered != 0
                        or origin_data.get('modelId') != request['model']
                        or origin_data.get('modelRevision') != 'provider-managed-unpinned'):
                    raise ValueError('Veo request differs from the one frozen text-only generation')
            else:
                run = next(run for run in generation['runs'] if run['id'] == slot)
                mapping = {'negative_prompt': 'negativePrompt', 'num_frames': 'numFrames',
                           'num_inference_steps': 'numInferenceSteps', 'guidance_scale': 'guidanceScale',
                           'max_sequence_length': 'maxSequenceLength'}
                expected_run = {mapping.get(key, key): value for key, value in run.items() if key != 'purpose'}
                expected_run.update({'stage': 'normal', 'flowShift': generation['wanScheduler']['flow_shift']})
                if (run.get('purpose') != 'evaluation-parent' or raw.get('stage') != 'normal'
                        or raw.get('run') != expected_run or raw.get('inputMedia') != []
                        or raw.get('eligibleAsEvaluationControl') is not True
                        or raw.get('modelId') != generation['modelId']
                        or raw.get('modelRevision') != generation['revision']
                        or raw.get('scriptSha256') != generation['scriptSha256']
                        or raw.get('requirementsLockSha256') != generation['requirementsLockSha256']
                        or origin_data.get('modelId') != generation['modelId']
                        or origin_data.get('modelRevision') != generation['revision']):
                    raise ValueError('Wan parent is not the exact frozen normal text-only generation')
    canonical = build.get('canonicalParents', {})
    if set(canonical) != ancestors:
        raise ValueError('Construction receipt lacks an intermediate parent')
    for parent in parents:
        record = canonical[parent['parentId']]
        indices = record.get('sourceFrameIndices', [])
        if (any(record.get(key) != value for key, value in parent.items())
                or len(indices) != 120 or any(type(i) is not int or i < 0 for i in indices)
                or any(b < a for a, b in zip(indices, indices[1:]))
                or sha(local_path(record['canonicalPath'])) != record['canonicalSha256']):
            raise ValueError('Intermediate parent source identity or frame selection changed')
    lineage_spec = importlib.util.spec_from_file_location('shot_fps_evidence_check', ROOT / 'scripts/ffmpeg-fps-lineage.py')
    lineage_module = importlib.util.module_from_spec(lineage_spec)
    lineage_spec.loader.exec_module(lineage_module)
    masters = {row['caseId'].rsplit('/', 1)[0]: row for row in rows if row['quality'] == 'master'}
    for row in rows:
        if (row.get('sourcePlanSha256') != required_hashes['sourcePlanSha256']
                or row.get('generationPlanSha256') != required_hashes['generationPlanSha256']
                or row.get('groupId') != 'fresh-shot-study-linked-family'):
            raise ValueError('Manifest source-plan or ancestry-family identity changed')
        construction_path = local_path(row['constructionReceiptPath'])
        if sha(construction_path) != row['constructionReceiptSha256']:
            raise ValueError('Construction receipt changed')
        construction = json.loads(construction_path.read_text())
        frames = read_lineage(row, plan)
        if (construction.get('operation') != row['composition']
                or construction.get('hostCanonicalSha256') != canonical[row['hostId']]['canonicalSha256']
                or construction.get('donorCanonicalSha256') !=
                (canonical[row['donorId']]['canonicalSha256'] if row['donorId'] else None)):
            raise ValueError('Construction uses another intermediate parent or operation')
        if row['quality'] == 'master':
            expected_indices = list(range(120))
        else:
            master = masters[row['caseId'].rsplit('/', 1)[0]]
            log = construction_path.parent / 'encode.log'
            if (sha(log) != construction['fpsDebugLogSha256']
                    or construction.get('masterPath') != master['path']
                    or construction.get('masterSha256') != master['sha256']):
                raise ValueError('Quality derivative refers to another master or FPS trace')
            parsed = lineage_module.parse_fps_lineage(log.read_text(), 120, len(frames))
            expected_indices = parsed['inputIndices'] if isinstance(parsed, dict) else parsed
            if parsed != construction.get('fpsLineage'):
                raise ValueError('Saved FPS mapping differs from raw FFmpeg trace')
        if (construction.get('masterFrameIndices') != expected_indices
                or [frame['masterIndex'] for frame in frames] != expected_indices
                or construction.get('hostCanonicalFrameIndices') != expected_indices
                or construction.get('alpha') != [frame['donorAlpha'] for frame in frames]):
            raise ValueError('Construction and frame lineage do not match actual selected frames')
        donor_indices = [i if frame['donorAlpha'] > 0 else None for i, frame in zip(expected_indices, frames)]
        if construction.get('donorCanonicalFrameIndices') != donor_indices:
            raise ValueError('Donor indices differ from the frozen same-timeline insertion')
        for index, frame in zip(expected_indices, frames):
            if (frame['hostSourceFrame'] != canonical[row['hostId']]['sourceFrameIndices'][index]
                    or frame['donorSourceFrame'] !=
                    (canonical[row['donorId']]['sourceFrameIndices'][index] if frame['donorAlpha'] > 0 else None)):
                raise ValueError('Lineage reports an incorrect native parent frame')
    return rows, build


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def windows_for_shots(total_frames, fps, cut_indices):
    """Every boundary frame starts its new shot; unsupported shots remain visible."""
    if total_frames < 1 or fps not in (12, 24):
        raise ValueError('Study supports only declared 12/24 fps inputs')
    if sorted(set(cut_indices)) != cut_indices or any(i <= 0 or i >= total_frames for i in cut_indices):
        raise ValueError('Invalid or duplicate scene boundaries')
    boundaries = [0, *cut_indices, total_frames]
    if len(boundaries) - 1 > 128:
        raise ValueError('Registered shot bound exceeded; no truncation is allowed')
    shots, windows = [], []
    for number, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        length = end - start
        shot = {'shotIndex': number, 'startFrame': start, 'endFrameExclusive': end,
                'startSeconds': start / fps, 'endSeconds': end / fps,
                'supported': length >= fps and length >= 8}
        shots.append(shot)
        if not shot['supported']:
            shot['reason'] = 'Shot shorter than one second or eight source frames'
            continue
        width = min(4 * fps, length)
        starts = list(range(0, length - width + 1, 2 * fps))
        if starts[-1] != length - width:
            starts.append(length - width)
        for local_start in starts:
            first = start + local_start
            indices = [first + (i * (width - 1)) // 15 for i in range(16)]
            windows.append({'windowIndex': len(windows), 'shotIndex': number,
                            'startFrame': first, 'endFrameExclusive': first + width,
                            'requestedFrameIndices': indices,
                            'duplicatedRequestedIndices': 16 - len(set(indices))})
    if len(windows) > MAX_WINDOWS:
        raise ValueError('Registered per-video window bound exceeded')
    return shots, windows


def printed_time_matches(token, actual):
    """FFmpeg's human-readable time is rounded; integer frame PTS is authoritative."""
    try:
        printed = Decimal(token)
        if not printed.is_finite():
            return False
        actual = Fraction(actual)
        exact = Decimal(actual.numerator) / Decimal(actual.denominator)
        half_unit = Decimal(10) ** printed.as_tuple().exponent / 2
        return abs(printed - exact) <= half_unit + Decimal('1e-20')
    except (InvalidOperation, ValueError, TypeError, ZeroDivisionError):
        return False


def parse_scene_metadata(text, total_frames, pts_times, tick):
    records = []
    current = None
    frame_line = re.compile(r'^frame:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(\S+)\s*$')
    for line in text.splitlines():
        match = frame_line.match(line.strip())
        if match:
            current = {'index': int(match[1]), 'filterPts': int(match[2]),
                       'printedTime': match[3], 'timeSeconds': float(match[3]), 'metadata': {}}
            records.append(current)
        elif line.startswith('lavfi.scd.'):
            if current is None or '=' not in line:
                raise ValueError('Scene metadata appeared without its frame')
            key, value = line.split('=', 1)
            if key in current['metadata'] and current['metadata'][key] != value:
                raise ValueError('Conflicting duplicate scene metadata')
            current['metadata'][key] = value
        elif line.strip():
            raise ValueError('Unexpected scene metadata output')
    if len(records) != total_frames:
        raise ValueError('Scene detector did not report every native frame')
    cuts = []
    for index, row in enumerate(records):
        if row['index'] != index or not math.isfinite(row['timeSeconds']):
            raise ValueError('Scene metadata frame order is invalid')
        actual = Fraction(pts_times[index])
        if (Fraction(row['filterPts']) * Fraction(tick) != actual
                or not printed_time_matches(row['printedTime'], actual)):
            raise ValueError('Scene metadata integer PTS differs from native frame PTS')
        metadata = row['metadata']
        for name in ('lavfi.scd.score', 'lavfi.scd.mafd'):
            if (name not in metadata or not math.isfinite(float(metadata[name]))
                    or not 0 <= float(metadata[name]) <= 100):
                raise ValueError('Missing or nonfinite scene diagnostic')
        # Presence is FFmpeg's internal threshold decision. Printed scores are rounded.
        if 'lavfi.scd.time' in metadata:
            if not printed_time_matches(metadata['lavfi.scd.time'], actual):
                raise ValueError('Scene-boundary timestamp mismatch')
            if index:
                cuts.append(index)
    return records, cuts


def inspect_video(path, row, cv2, np, video_io, artifact_dir):
    if path.stat().st_size > 50_000_000 or sha(path) != row['sha256']:
        raise ValueError('Media SHA or byte bound failed')
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v', '-show_streams',
        '-show_frames', '-show_entries',
        'stream=width,height,pix_fmt,sample_aspect_ratio,time_base,r_frame_rate,avg_frame_rate,nb_frames:stream_side_data=rotation:frame=best_effort_timestamp,duration,pkt_duration,width,height,pix_fmt',
        '-of', 'json', str(path),
    ], timeout=20))
    streams = probe.get('streams', [])
    if len(streams) != 1:
        raise ValueError('Expected one video stream')
    stream = streams[0]
    if any(s.get('rotation', 0) != 0 for s in stream.get('side_data_list', [])):
        raise ValueError('Rotated media outside frozen study')
    rate = Fraction(stream['avg_frame_rate'])
    if rate not in (Fraction(12), Fraction(24)) or Fraction(stream['r_frame_rate']) != rate:
        raise ValueError('Unexpected study frame rate')
    fps = int(rate)
    expected = fps * 5
    frames = probe['frames']
    if len(frames) != expected or int(stream['nb_frames']) != expected:
        raise ValueError('Study media must have exactly five seconds of native frames')
    severe = row['quality'] == 'severe'
    if ((stream['width'], stream['height']) != ((360, 202) if severe else (640, 360))
            or fps != (12 if severe else 24) or stream.get('pix_fmt') != 'yuv420p'
            or stream.get('sample_aspect_ratio') not in ('1:1', '1/1')):
        raise ValueError('Dimensions, rate, pixel format or SAR differ from this quality recipe')
    tick = Fraction(stream['time_base'])
    if tick <= 0:
        raise ValueError('Invalid native time base')
    pts = [Fraction(int(f['best_effort_timestamp'])) * tick for f in frames]
    if (any(b <= a for a, b in zip(pts, pts[1:]))
            or any(abs(t - Fraction(i, fps)) > tick for i, t in enumerate(pts))):
        raise ValueError('Native PTS are not zero-origin registered CFR')
    for frame in frames:
        duration = frame.get('duration', frame.get('pkt_duration'))
        if (duration is None or int(duration) <= 0 or abs(int(duration) * tick - Fraction(1, fps)) > tick
                or frame.get('width') != stream['width'] or frame.get('height') != stream['height']
                or frame.get('pix_fmt') != stream['pix_fmt']):
            raise ValueError('Native frame duration, dimensions or pixel format are ambiguous')
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
               '-i', str(path), '-map', '0:v:0', '-an', '-vf',
               'scdet=threshold=10:sc_pass=0,metadata=mode=print:file=-',
               '-fps_mode', 'passthrough', '-f', 'null', '-']
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    (artifact_dir / 'scdet.txt').write_text(result.stdout)
    (artifact_dir / 'scdet-stderr.txt').write_text(result.stderr)
    records, cuts = parse_scene_metadata(result.stdout, expected, pts, tick)
    shots, windows = windows_for_shots(expected, fps, cuts)
    lineage = read_lineage(row)
    wanted = set(i for window in windows for i in window['requestedFrameIndices'])
    captured, all_hashes = {}, []
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError('Cannot open video for strict RGB decoding')
    try:
        for index in range(expected):
            ok, bgr = cap.read()
            if not ok or bgr.shape != (stream['height'], stream['width'], 3):
                raise ValueError(f'Native decode failed at frame {index}')
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            all_hashes.append(hashlib.sha256(rgb.tobytes()).hexdigest())
            if index in wanted:
                captured[index] = rgb
        if cap.read()[0]:
            raise ValueError('Decoder produced more frames than declared')
    finally:
        cap.release()
    if set(captured) != wanted:
        raise ValueError('Missing actual requested frames')
    tensors = []
    for window in windows:
        selected = np.stack([captured[i] for i in window['requestedFrameIndices']])
        tensor = video_io.preprocess_frames(selected, height=224, width=224)
        if tuple(tensor.shape) != (16, 3, 224, 224):
            raise ValueError('Official preprocessing shape differs')
        tensors.append(tensor.unsqueeze(0))
        window.update({'sourceTimesSeconds': [float(pts[i]) for i in window['requestedFrameIndices']],
                       'rgbFrameSha256': [all_hashes[i] for i in window['requestedFrameIndices']],
                       'normalizedTensorSha256': hashlib.sha256(tensor.numpy().tobytes()).hexdigest()})
        window.update(window_lineage(window, lineage))
    receipt = {'mediaSha256': row['sha256'], 'quality': row['quality'], 'probe': probe,
               'frameLineagePath': row['frameLineagePath'], 'frameLineageSha256': row['frameLineageSha256'],
               'lineageMeaning': 'Construction weights before lossy encoding; not decoded-pixel probabilities or model inputs',
               'nativePts': [int(frame['best_effort_timestamp']) for frame in frames],
               'nativeTimeBase': str(tick), 'fps': fps,
               'timelineEndRational': str(Fraction(expected, fps)),
               'scdetCommand': command, 'sceneMetadata': records,
               'cutIndices': cuts, 'shots': shots, 'windows': windows,
               'nativeFrameSha256': all_hashes, 'nativeFramesDecoded': expected,
               'nativeContentDuplicateFrames': expected - len(set(all_hashes)),
               'coverageComplete': all(s['supported'] for s in shots),
               'scdetTextSha256': sha(artifact_dir / 'scdet.txt')}
    (artifact_dir / 'inspection.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return tensors, receipt


def evaluate_windows(model, tensors, windows, torch, outcomes=None):
    if len(tensors) != len(windows):
        raise ValueError('Not every planned window has its tensor')
    outcomes = [] if outcomes is None else outcomes
    for position, (window, tensor) in enumerate(zip(windows, tensors)):
        outcome = {'windowIndex': window['windowIndex'], 'status': 'error'}
        outcome.update({key: window[key] for key in ('sampledDonorFrames', 'sampledFullyDonorFrames',
                       'sampledBlendEdgeFrames', 'sampledKnownAiFrames', 'sampledFullyAiFrames') if key in window})
        try:
            if not torch.isfinite(tensor).all():
                raise ValueError('Nonfinite preprocessed window')
            with torch.inference_mode():
                outputs = model(tensor)
            outcome.update({'status': 'ok', 'syntheticScore': float(outputs['ai_probability'].item()),
                            'fusedLogit': float(outputs['ai_logit'].item())})
            if not valid_score(outcome):
                raise ValueError('Invalid fused score/logit contract')
        except (TimeoutError, MemoryError) as error:
            # Global resource failures terminate this video; ordinary individual
            # forward/output failures below must not suppress later valid windows.
            outcome.update({'status': 'error', 'error': str(error), 'errorType': type(error).__name__})
            outcomes.append(outcome)
            for remaining in windows[position + 1:]:
                outcomes.append({'windowIndex': remaining['windowIndex'], 'status': 'not_run',
                                 'error': 'Global resource failure ended this video',
                                 'errorType': type(error).__name__})
            raise
        except Exception as error:
            outcome.update({'status': 'error', 'error': str(error), 'errorType': type(error).__name__})
        for name in ('syntheticScore', 'fusedLogit'):
            if name in outcome and not finite_number(outcome[name]):
                outcome.setdefault('invalidRawOutputs', {})[name] = repr(outcome[name])
                outcome[name] = None
        outcomes.append(outcome)
    return outcomes


def validate_inspection(row, truth):
    path = local_path(row['inspectionPath'])
    if sha(path) != row.get('inspectionSha256'):
        raise ValueError('Prior gate inspection evidence changed')
    inspection = json.loads(path.read_text())
    lineage = read_lineage(truth)
    fps = 12 if truth['quality'] == 'severe' else 24
    count = 5 * fps
    if (inspection.get('mediaSha256') != truth['sha256'] or inspection.get('quality') != truth['quality']
            or inspection.get('frameLineagePath') != truth['frameLineagePath']
            or inspection.get('frameLineageSha256') != truth['frameLineageSha256']
            or inspection.get('fps') != fps or inspection.get('nativeFramesDecoded') != count
            or row.get('nativeFramesDecoded') != count
            or inspection.get('timelineEndRational') != '5'
            or len(inspection.get('nativeFrameSha256', [])) != count):
        raise ValueError('Prior gate inspection is not complete for this file')
    scene_text = path.parent / 'scdet.txt'
    if sha(scene_text) != inspection['scdetTextSha256']:
        raise ValueError('Prior gate raw scene metadata changed')
    tick = Fraction(inspection['nativeTimeBase'])
    pts = [Fraction(int(value)) * tick for value in inspection['nativePts']]
    if (len(pts) != count or tick <= 0 or any(b <= a for a, b in zip(pts, pts[1:]))
            or any(abs(value - Fraction(i, fps)) > tick for i, value in enumerate(pts))):
        raise ValueError('Prior gate native frame timeline is incomplete')
    scene, cuts = parse_scene_metadata(scene_text.read_text(), count, pts, tick)
    shots, windows = windows_for_shots(count, fps, cuts)
    if (scene != inspection['sceneMetadata'] or cuts != inspection['cutIndices']
            or shots != inspection['shots'] or not all(s['supported'] for s in shots)
            or inspection.get('coverageComplete') is not True
            or len(windows) != len(inspection['windows'])):
        raise ValueError('Prior gate shot/window coverage differs from its raw scene evidence')
    for expected, actual in zip(windows, inspection['windows']):
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError('Prior gate changed or omitted a required window')
        if any(actual.get(key) != value for key, value in window_lineage(expected, lineage).items()):
            raise ValueError('Prior gate sampled source contribution differs from frame lineage')
        indices = expected['requestedFrameIndices']
        if (actual.get('rgbFrameSha256') != [inspection['nativeFrameSha256'][i] for i in indices]
                or actual.get('sourceTimesSeconds') != [float(pts[i]) for i in indices]
                or not re.fullmatch(r'[a-f0-9]{64}', actual.get('normalizedTensorSha256', ''))):
            raise ValueError('Prior gate lacks actual window frame/tensor identity')
    scores = row.get('windowScores', [])
    if (not windows or len(scores) != len(windows)
            or row.get('plannedWindowCount') != len(windows)
            or [score.get('windowIndex') for score in scores] != [window['windowIndex'] for window in windows]
            or any(not valid_score(score) for score in scores)):
        raise ValueError('Prior gate has missing, failed or invalid raw window results')
    for score, window in zip(scores, inspection['windows']):
        if any(score.get(key) != window[key] for key in ('sampledDonorFrames', 'sampledFullyDonorFrames',
               'sampledBlendEdgeFrames', 'sampledKnownAiFrames', 'sampledFullyAiFrames')):
            raise ValueError('Prior gate score diagnostics misstate sampled origin contribution')
    return scores


def gate_check(path, expected_stage, recipe_hash):
    receipt = json.loads(Path(path).read_text())
    if (receipt.get('stage') != expected_stage or receipt.get('status') != 'passed'
            or receipt.get('selected') != STAGES[expected_stage]
            or receipt.get('completed') != STAGES[expected_stage]
            or receipt.get('errors') != 0 or receipt.get('incorrect') != 0
            or receipt.get('frozenSnapshotAndWeightsUnchanged') is not True
            or receipt.get('workingRunnerUnchanged') is not True
            or receipt.get('recipeFingerprint') != recipe_hash
            or fingerprint(receipt.get('configuration')) != recipe_hash):
        raise ValueError('Prior stage gate failed or used another recipe')
    config = receipt['configuration']
    required = {**fixed_policy(), 'protocolSha256': sha(PROTOCOL),
                'generationPlanSha256': sha(GENERATION_PLAN), 'sourcePlanSha256': sha(SOURCE_PLAN)}
    if any(config.get(key) != value for key, value in required.items()):
        raise ValueError('Saved gate does not bind the expected model, policy and frozen plans')
    expected_sources = expected_source_entries()
    if receipt.get('sourceFiles') != expected_sources:
        raise ValueError('Saved gate source snapshot differs from this frozen evaluator')
    loading = receipt.get('modelLoading', {})
    if (loading.get('strict') is not True or loading.get('tensorCount') != 467
            or loading.get('fullBackboneSupplied') is not True
            or loading.get('architectureOnlyInitialization') is not True):
        raise ValueError('Saved gate lacks complete strict checkpoint-loading evidence')
    if (json.loads(GENERATION_PLAN.read_text()).get('frozen') is not True
            or json.loads(SOURCE_PLAN.read_text()).get('frozen') is not True):
        raise ValueError('Saved gate plans are not frozen')
    output = local_path(receipt['outputPath'])
    manifest = local_path(receipt['manifestPath'])
    if sha(output) != receipt['outputSha256'] or sha(manifest) != receipt['manifestSha256']:
        raise ValueError('Prior gate evidence changed')
    build_receipt = local_path(receipt['buildReceiptPath'])
    if sha(build_receipt) != receipt['buildReceiptSha256']:
        raise ValueError('Prior gate build receipt changed')
    plan = json.loads(SOURCE_PLAN.read_text())
    references, _ = validate_manifest(manifest, expected_stage, plan, build_receipt)
    snapshot = local_path(receipt['sourceSnapshot'])
    for entry in receipt['sourceFiles'] + receipt['snapshotEvidenceFiles']:
        if not (snapshot / entry['path']).resolve().is_relative_to(snapshot) or sha(snapshot / entry['path']) != entry['sha256']:
            raise ValueError('Prior gate immutable source/evidence snapshot changed')
    if fingerprint(receipt['sourceFiles']) != receipt['configuration']['sourceFingerprint']:
        raise ValueError('Prior gate source list differs from recipe')
    rows = read_rows(output)
    expected = {r['id']: r for r in references}
    if len(rows) != STAGES[expected_stage] or {r['id'] for r in rows} != set(expected):
        raise ValueError('Prior gate cohort changed')
    for row in rows:
        truth = expected[row['id']]
        positive = truth['label'] in ('ai', 'mixed')
        if (row.get('error') or row.get('coverageComplete') is not True or row.get('correct') is not True
                or any(row.get(key) != value for key, value in truth.items())
                or row['decision'] != ('ai' if positive else 'not_ai')
                or row['recipeFingerprint'] != recipe_hash):
            raise ValueError('Prior stage contains a failed outcome')
        scores = validate_inspection(row, truth)
        if any(s['syntheticScore'] >= 0.5 for s in scores) != positive:
            raise ValueError('Prior gate outcome contradicts raw scores')
    return receipt


def snapshot_sources(output, manifest, build_receipt):
    snapshot = output.with_suffix('.source')
    snapshot.mkdir(parents=True, exist_ok=False)
    expected_source_entries()
    sources = common_sources()
    entries = []
    for path, name in sources:
        shutil.copyfile(path, snapshot / name)
        entries.append({'path': name, 'sha256': sha(snapshot / name)})
    vendor = json.loads(VENDOR_RECEIPT.read_text())
    for name, expected in vendor['files'].items():
        path = ROOT / 'eval/vendor/aegis' / name
        if sha(path) != expected['sha256']:
            raise ValueError('Pinned upstream source changed')
        target = snapshot / 'vendor' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        entries.append({'path': 'vendor/' + name, 'sha256': sha(target)})
    evidence = []
    for path, name in ((manifest, 'manifest.jsonl'), (build_receipt, 'build-receipt.json')):
        shutil.copyfile(path, snapshot / name)
        evidence.append({'path': name, 'sha256': sha(snapshot / name)})
    (snapshot / 'source-manifest.json').write_text(json.dumps(entries + evidence, indent=2) + '\n')
    return snapshot, entries, evidence


def resource_watchdog(guard, receipt, rows, persist):
    while not guard['stopped']:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss *= 1 if sys.platform == 'darwin' else 1024
        reason = None
        if rss > MAX_RSS:
            reason = 'Detector worker exceeded the 8 GiB RSS limit'
        elif guard['deadline'] is not None and time.monotonic() > guard['deadline']:
            reason = 'Detector video exceeded the 120-second deadline'
        if reason:
            # Hard stop also interrupts native inference when Python's alarm
            # handler cannot run. An incomplete receipt cannot qualify as a gate.
            receipt.update({'status': 'resource-failed', 'error': reason,
                            'unfinishedSelectedIds': [row['id'] for row in rows[receipt['completed']:]],
                            'finishedAtUnix': time.time()})
            persist()
            print(json.dumps({'fatalResourceFailure': reason}), file=sys.stderr, flush=True)
            os._exit(124)
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, choices=STAGES)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--build-receipt', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--protocol-sha256', required=True)
    parser.add_argument('--negative-gate')
    parser.add_argument('--veo-gate')
    args = parser.parse_args()
    output, manifest = local_path(args.output), local_path(args.manifest)
    build_receipt_path = local_path(args.build_receipt)
    receipt_path = output.with_suffix('.receipt.json')
    if output.exists() or receipt_path.exists() or output.with_suffix('.source').exists():
        raise ValueError('Prior study evidence is immutable; use a fresh output path')
    if sha(BASE) != BASE_SHA or sha(WEIGHTS) != WEIGHTS_SHA or sha(PROTOCOL) != args.protocol_sha256:
        raise ValueError('Frozen source/model/protocol hash mismatch')
    generation = json.loads(GENERATION_PLAN.read_text())
    plan = json.loads(SOURCE_PLAN.read_text())
    if generation.get('frozen') is not True or plan.get('frozen') is not True:
        raise ValueError('All prospective plans must be frozen before detector inference')
    rows, _ = validate_manifest(manifest, args.stage, plan, build_receipt_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot, sources, snapshot_evidence = snapshot_sources(output, manifest, build_receipt_path)
    spec = importlib.util.spec_from_file_location('aegis_study_base', snapshot / 'aegis-base.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.ROOT = ROOT
    base.RUNTIME = ROOT / 'eval/vendor/aegis-runtime'
    cv2, np, torch, timm, load_file, versions, timm_sources = base.runtime_modules()
    # GCD ignores positive limits and reports the processor count. Zero is the
    # documented way to disable OpenCV parallelism on this frozen Mac backend.
    cv2.setNumThreads(0)
    info = cv2.getBuildInformation()
    backend = re.search(r'^\s*Parallel framework:\s*(.+)$', info, re.M)
    if cv2.getNumThreads() != 1 or backend is None or backend[1].strip() != 'GCD':
        raise ValueError('Expected verified sequential OpenCV GCD execution')
    ffmpeg = Path(shutil.which('ffmpeg')).resolve()
    ffprobe = Path(shutil.which('ffprobe')).resolve()
    recipe = {**fixed_policy(),
              'protocolSha256': args.protocol_sha256,
              'generationPlanSha256': sha(GENERATION_PLAN), 'sourcePlanSha256': sha(SOURCE_PLAN),
              'sourceFingerprint': fingerprint(sources), 'runtimeVersions': versions,
              'timmSourceFingerprint': fingerprint(timm_sources),
              'ffmpegSha256': sha(ffmpeg),
              'ffprobeSha256': sha(ffprobe),
              'ffmpegVersion': subprocess.check_output([str(ffmpeg), '-version'], text=True).splitlines()[0],
              'opencvThreadsReported': cv2.getNumThreads(), 'opencvParallelFramework': backend[1].strip(),
              'opencvBuildInformationSha256': hashlib.sha256(info.encode()).hexdigest()}
    recipe_hash = fingerprint(recipe)
    gates = []
    if args.stage != 'negative-45':
        if not args.negative_gate:
            raise ValueError('Successful negative gate is required')
        gates.append(gate_check(local_path(args.negative_gate), 'negative-45', recipe_hash))
    if args.stage == 'wan-30':
        if not args.veo_gate:
            raise ValueError('Successful Veo gate is required')
        gates.append(gate_check(local_path(args.veo_gate), 'veo-30', recipe_hash))
    receipt = {'stage': args.stage, 'status': 'running', 'configuration': recipe,
               'recipeFingerprint': recipe_hash, 'sourceFiles': sources,
               'snapshotEvidenceFiles': snapshot_evidence,
               'sourceSnapshot': str(snapshot.relative_to(ROOT)),
               'selected': len(rows), 'completed': 0, 'errors': 0, 'incorrect': 0,
               'manifestPath': str(manifest.relative_to(ROOT)), 'manifestSha256': sha(manifest),
               'buildReceiptPath': str(build_receipt_path.relative_to(ROOT)),
               'buildReceiptSha256': sha(build_receipt_path),
               'outputPath': str(output.relative_to(ROOT)), 'startedAtUnix': time.time(),
               'priorStageReceipts': [{'stage': g['stage'], 'outputSha256': g['outputSha256']} for g in gates]}
    def persist():
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    persist()
    guard = {'deadline': None, 'stopped': False}
    threading.Thread(target=resource_watchdog, args=(guard, receipt, rows, persist), daemon=True).start()
    try:
        model, video_io, load_receipt = base.load_model(snapshot, WEIGHTS, torch, timm, load_file)
        receipt['modelLoading'] = load_receipt
        persist()
    except Exception as error:
        receipt.update({'status': 'setup-failed', 'error': str(error), 'errorType': type(error).__name__})
        persist()
        raise
    artifact_root = output.with_suffix('.artifacts')
    artifact_root.mkdir(exist_ok=False)
    def timed_out(signum, frame):
        raise TimeoutError('Per-video operation exceeded 120 seconds')
    signal.signal(signal.SIGALRM, timed_out)
    with output.open('x') as stream:
        for row in rows:
            result = {**row, 'recipeFingerprint': recipe_hash, 'windowScores': [],
                      'decision': 'abstain', 'coverageComplete': False}
            started = time.monotonic()
            artifact_dir = artifact_root / row['id']
            artifact_dir.mkdir(exist_ok=False)
            guard['deadline'] = time.monotonic() + VIDEO_TIMEOUT
            signal.alarm(VIDEO_TIMEOUT)
            try:
                tensors, inspection = inspect_video(ROOT / row['path'], row, cv2, np, video_io, artifact_dir)
                result['inspectionCoverageComplete'] = inspection['coverageComplete']
                result['inspectionPath'] = str((artifact_dir / 'inspection.json').relative_to(ROOT))
                result['inspectionSha256'] = sha(artifact_dir / 'inspection.json')
                result['nativeFramesDecoded'] = inspection['nativeFramesDecoded']
                result['unsupportedShots'] = [s for s in inspection['shots'] if not s['supported']]
                result['plannedWindowCount'] = len(inspection['windows'])
                evaluate_windows(model, tensors, inspection['windows'], torch, result['windowScores'])
                failed_windows = [window for window in result['windowScores'] if not valid_score(window)]
                result['coverageComplete'] = inspection['coverageComplete'] and not failed_windows
                if failed_windows:
                    result['error'] = 'One or more planned windows failed; every other valid window was attempted'
                    result['errorType'] = 'WindowFailures'
                elif not inspection['coverageComplete']:
                    result['error'] = 'Unsupported short-shot coverage'
                    result['errorType'] = 'UnsupportedCoverage'
            except Exception as error:
                result.update({'error': str(error), 'errorType': type(error).__name__})
            finally:
                signal.alarm(0)
                guard['deadline'] = None
            positive = any(valid_score(w) and w['syntheticScore'] >= 0.5 for w in result['windowScores'])
            if positive:
                result['decision'] = 'ai'
            elif result['coverageComplete'] and not result.get('error') and result['windowScores']:
                result['decision'] = 'not_ai'
            truth_positive = row['label'] in ('ai', 'mixed')
            result['correct'] = result['decision'] == ('ai' if truth_positive else 'not_ai')
            result['elapsedMs'] = round((time.monotonic() - started) * 1000)
            result['processMaxRssBytesMacOS'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            receipt['completed'] += 1
            receipt['errors'] += bool(result.get('error'))
            receipt['incorrect'] += not result['correct']
            stream.write(json.dumps(result, sort_keys=True, allow_nan=False) + '\n')
            stream.flush()
            persist()
            print(json.dumps({'id': row['id'], 'completed': receipt['completed'], 'selected': len(rows),
                              'elapsedMs': result['elapsedMs'], 'error': result.get('error')}), flush=True)
    guard['stopped'] = True
    unchanged = (sha(WEIGHTS) == WEIGHTS_SHA
                 and all(sha(snapshot / e['path']) == e['sha256'] for e in sources + snapshot_evidence)
                 and sha(GENERATION_PLAN) == recipe['generationPlanSha256']
                 and sha(SOURCE_PLAN) == recipe['sourcePlanSha256']
                 and sha(PROTOCOL) == args.protocol_sha256
                 and all(sha(local_path(row['path'])) == row['sha256'] for row in rows)
                 and sha(ffmpeg) == recipe['ffmpegSha256'] and sha(ffprobe) == recipe['ffprobeSha256'])
    working_unchanged = sha(Path(__file__)) == sha(snapshot / 'eval-aegis-shots.py')
    receipt.update({'finishedAtUnix': time.time(), 'outputSha256': sha(output),
                    'frozenSnapshotAndWeightsUnchanged': unchanged,
                    'workingRunnerUnchanged': working_unchanged,
                    'status': 'passed' if (receipt['completed'] == len(rows) and not receipt['errors']
                                           and not receipt['incorrect'] and unchanged and working_unchanged) else 'failed'})
    persist()
    if receipt['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
