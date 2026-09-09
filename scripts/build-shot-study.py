#!/usr/bin/env python3
"""Construct frozen fresh-origin controls without invoking a detector."""
import argparse
from bisect import bisect_right
from fractions import Fraction
import hashlib
import importlib.util
import importlib.metadata
import json
import math
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PLAN = ROOT / 'eval/fixtures/shot-study-source-plan.json'
GENERATION_PLAN = ROOT / 'eval/fixtures/shot-study-generation-plan.json'
PROTOCOL = ROOT / 'eval/AEGIS_SHOT_EVALUATION_PROTOCOL.md'
LINEAGE = ROOT / 'scripts/ffmpeg-fps-lineage.py'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def local(path):
    result = (ROOT / path).resolve()
    if not result.is_relative_to(ROOT):
        raise ValueError('Study media and receipts must remain in workspace')
    return result


def write_json(path, data):
    with Path(path).open('x') as f:
        json.dump(data, f, indent=2)
        f.write('\n')


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_frames',
        '-show_entries', 'stream=index,codec_type,width,height,sample_aspect_ratio,time_base,avg_frame_rate,duration,nb_frames:stream_side_data=rotation:frame=media_type,best_effort_timestamp,duration,pkt_duration',
        '-of', 'json', str(path),
    ], timeout=30))


def parent_record(parent_id, specification, wrappers, gen_plan_sha, protocol_sha):
    if 'generationSlot' not in specification:
        record = {k: specification[k] for k in ['path', 'sha256', 'originReceiptPath', 'originReceiptSha256']}
    else:
        if specification['generationSlot'] != parent_id:
            raise ValueError('Generated source-plan key and slot disagree')
        wrapper_path = wrappers.get(parent_id)
        if not wrapper_path:
            raise ValueError(f'Missing declared generated parent receipt: {parent_id}')
        wrapper = json.loads(wrapper_path.read_text())
        if (wrapper.get('status') != 'completed' or wrapper.get('generationSlot') != parent_id
                or wrapper.get('generationPlanSha256') != gen_plan_sha
                or wrapper.get('evaluationProtocolSha256') != protocol_sha
                or wrapper.get('inputMedia') != []):
            raise ValueError('Generated parent wrapper does not match frozen text-only study')
        raw_ref = wrapper['rawGenerationReceipt']
        raw_path = local(raw_ref['path'])
        if sha(raw_path) != raw_ref['sha256']:
            raise ValueError('Raw generation receipt changed')
        raw = json.loads(raw_path.read_text())
        if (raw.get('status') != 'succeeded' or raw.get('generationSlot') != parent_id
                or raw.get('generationPlanSha256') != gen_plan_sha
                or raw.get('evaluationProtocolSha256') != protocol_sha
                or raw.get('inputMedia') != [] or raw.get('output') != wrapper['output']):
            raise ValueError('Raw generation receipt disagrees with parent wrapper')
        generation = json.loads(GENERATION_PLAN.read_text())
        if parent_id.startswith('V'):
            declared = next(v for v in generation['veoRuns'] if v['id'] == parent_id)
            operation = raw.get('operation', {})
            response = operation.get('response', {})
            videos = response.get('generatedVideos')
            filtered_count = response.get('raiMediaFilteredCount', 0)
            if (wrapper.get('modelId') != declared['request']['model']
                    or wrapper.get('modelRevision') != 'provider-managed-unpinned'
                    or raw.get('scriptSha256') != generation['veoScriptSha256']
                    or raw.get('request') != declared['request'] or operation.get('done') is not True
                    or operation.get('error') is not None
                    or not isinstance(videos, list) or len(videos) != 1
                    or type(filtered_count) is not int or filtered_count != 0):
                raise ValueError('Veo origin does not match its sole registered request')
        else:
            declared = next(v for v in generation['runs'] if v['id'] == parent_id)
            mapping = {'prompt': 'prompt', 'negative_prompt': 'negativePrompt', 'seed': 'seed',
                       'width': 'width', 'height': 'height', 'num_frames': 'numFrames',
                       'num_inference_steps': 'numInferenceSteps', 'guidance_scale': 'guidanceScale',
                       'max_sequence_length': 'maxSequenceLength', 'fps': 'fps',
                       'device': 'device', 'dtype': 'dtype', 'threads': 'threads'}
            if (wrapper.get('modelId') != generation['modelId']
                    or wrapper.get('modelRevision') != generation['revision']
                    or raw.get('modelId') != generation['modelId']
                    or raw.get('modelRevision') != generation['revision']
                    or raw.get('scriptSha256') != generation['scriptSha256']
                    or raw.get('requirementsLockSha256') != generation['requirementsLockSha256']
                    or raw.get('eligibleAsEvaluationControl') is not True
                    or raw.get('stage') != 'normal'
                    or any(raw.get('run', {}).get(target) != declared[source] for source, target in mapping.items())):
                raise ValueError('Wan origin does not match registered normal generation')
        record = {'path': wrapper['output']['path'], 'sha256': wrapper['output']['sha256'],
                  'originReceiptPath': str(wrapper_path.relative_to(ROOT)), 'originReceiptSha256': sha(wrapper_path)}
    record['parentId'] = parent_id
    for field, hash_field in [('path', 'sha256'), ('originReceiptPath', 'originReceiptSha256')]:
        if sha(local(record[field])) != record[hash_field]:
            raise ValueError(f'Parent media or origin record changed: {parent_id}')
    return record


def encode_rgb(frames, path, log_path, np):
    if path.exists() or tuple(frames.shape) != (120, 360, 640, 3) or frames.dtype != np.uint8:
        raise ValueError('Fresh output and exactly 120 canonical RGB frames required')
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-video_size', '640x360',
               '-framerate', '24', '-i', 'pipe:0', '-an', '-vf', 'setsar=1',
               '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-threads', '2',
               '-pix_fmt', 'yuv420p', '-r', '24', '-fps_mode', 'cfr', '-map_metadata', '-1',
               '-movflags', '+faststart', str(path)]
    process = subprocess.run(command, input=frames.tobytes(), capture_output=True, timeout=120)
    log_path.write_bytes(process.stderr)
    if process.returncode:
        raise ValueError(f'Canonical encoding failed: {process.returncode}')
    return command


def validate_output(path, fps, width, height):
    p = probe(path)
    if len(p['streams']) != 1 or p['streams'][0]['codec_type'] != 'video':
        raise ValueError('Study outputs must be one silent video stream')
    s = p['streams'][0]
    frames = p['frames']
    tick = Fraction(s['time_base'])
    if (s['width'] != width or s['height'] != height or Fraction(s['avg_frame_rate']) != fps
            or s.get('sample_aspect_ratio') != '1:1'
            or len(frames) != 5 * fps or int(s['nb_frames']) != 5 * fps
            or abs(Fraction(s['duration']) - 5) > tick):
        raise ValueError('Output dimensions, cadence, duration or frame count mismatch')
    for index, frame in enumerate(frames):
        if abs(Fraction(frame['best_effort_timestamp']) * tick - Fraction(index, fps)) > tick:
            raise ValueError('Output PTS failed exact CFR check')
        if abs(frame_duration(frame, tick) - Fraction(1, fps)) > tick:
            raise ValueError('Output frame duration failed exact CFR check')
    return p


def frame_duration(frame, tick):
    values = [Fraction(frame[key]) * tick for key in ('duration', 'pkt_duration')
              if key in frame]
    if not values or any(value <= 0 for value in values) or len(set(values)) != 1:
        raise ValueError('Positive, unambiguous native frame duration required')
    return values[0]


def source_frame_selection(native_frames, tick, specification):
    """Map centers only after verifying full coverage from measured durations."""
    times = [Fraction(f['best_effort_timestamp']) * tick for f in native_frames]
    if not times or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Parent requires strictly increasing native PTS')
    durations = [frame_duration(frame, tick) for frame in native_frames]
    # A new presentation supersedes the previous one even if metadata overlaps.
    ends = [min(t + d, times[i + 1]) if i + 1 < len(times) else t + d
            for i, (t, d) in enumerate(zip(times, durations))]
    offset = Fraction(str(specification['trimStartSeconds']))
    if offset < 0 or Fraction(str(specification['trimDurationSeconds'])) != 5:
        raise ValueError('Study requires a registered five-second excerpt')
    endpoint = offset + 5
    covered = offset
    for start, end in zip(times, ends):
        if end <= covered:
            continue
        if start > covered:
            break
        covered = end
        if covered >= endpoint:
            break
    if covered < endpoint:
        raise ValueError('Native frame durations leave missing excerpt coverage')
    centers = [offset + Fraction(2 * i + 1, 48) for i in range(120)]
    indices = [bisect_right(times, t) - 1 for t in centers]
    if any(i < 0 or not times[i] <= t < ends[i] for i, t in zip(indices, centers)):
        raise ValueError('Requested output center is not inside a real parent frame interval')
    return times, durations, ends, centers, indices


def decode_exact(path, count, width, height, cv2, np):
    cap = cv2.VideoCapture(str(path))
    frames = []
    try:
        for i in range(count):
            ok, frame = cap.read()
            if not ok or tuple(frame.shape) != (height, width, 3):
                raise ValueError(f'Exact output decode failed at frame {i}')
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if cap.read()[0]:
            raise ValueError('Output decode has extra frames')
    finally:
        cap.release()
    return np.stack(frames)


def canonical_parent(parent, specification, directory, cv2, np):
    source = local(parent['path'])
    p = probe(source)
    video_streams = [s for s in p['streams'] if s['codec_type'] == 'video']
    if len(video_streams) != 1:
        raise ValueError('Parent must have one video stream')
    s = video_streams[0]
    if any(d.get('rotation', 0) != 0 for d in s.get('side_data_list', [])):
        raise ValueError('Unregistered parent rotation')
    native_frames = [f for f in p['frames'] if f['media_type'] == 'video']
    tick = Fraction(s['time_base'])
    times, durations, ends, centers, indices = source_frame_selection(native_frames, tick, specification)
    ratio = s.get('sample_aspect_ratio', '1:1')
    sar = Fraction(ratio.replace(':', '/')) if ratio not in ('N/A', '0:1') else Fraction(1)
    if sar <= 0:
        raise ValueError('Invalid parent SAR')
    display_width = Fraction(s['width']) * sar
    scale = max(Fraction(640) / display_width, Fraction(360, s['height']))
    sw = 2 * math.ceil(display_width * scale / 2)
    sh = 2 * math.ceil(Fraction(s['height']) * scale / 2)
    x, y = (sw - 640) // 2, (sh - 360) // 2
    wanted = set(indices)
    captured, native_hash = {}, {}
    cap = cv2.VideoCapture(str(source))
    try:
        for index in range(max(indices) + 1):
            ok, bgr = cap.read()
            if not ok or bgr.shape != (s['height'], s['width'], 3):
                raise ValueError(f'Parent decode ended before actual requested frame {index}')
            if index in wanted:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                native_hash[index] = hashlib.sha256(rgb.tobytes()).hexdigest()
                resized = cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_CUBIC)
                captured[index] = resized[y:y + 360, x:x + 640].copy()
    finally:
        cap.release()
    if set(captured) != wanted:
        raise ValueError('Missing parent frames; no fabricated frames allowed')
    frames = np.stack([captured[i] for i in indices])
    path = directory / (parent['parentId'] + '.mp4')
    command = encode_rgb(frames, path, directory / (parent['parentId'] + '-encode.log'), np)
    output_probe = validate_output(path, 24, 640, 360)
    decoded = decode_exact(path, 120, 640, 360, cv2, np)
    record = {**parent, 'canonicalPath': str(path.relative_to(ROOT)), 'canonicalSha256': sha(path),
              'sourceFrameIndices': indices, 'sourceFrameTimes': [str(times[i]) for i in indices],
              'sourceFrameDurations': [str(durations[i]) for i in indices],
              'sourceFramePresentationEnds': [str(ends[i]) for i in indices],
              'outputFrameCenterSourceTimes': [str(t) for t in centers],
              'nativeRgbFrameSha256': [native_hash[i] for i in indices],
              'canonicalDecodedFrameSha256': [hashlib.sha256(f.tobytes()).hexdigest() for f in decoded],
              'geometry': {'sourceSar': str(sar), 'scaledWidth': sw, 'scaledHeight': sh,
                           'cropX': x, 'cropY': y, 'width': 640, 'height': 360,
                           'interpolation': 'cv2.INTER_CUBIC'},
              'sourceProbe': p, 'canonicalProbe': output_probe, 'encodeCommand': command}
    write_json(directory / (parent['parentId'] + '.json'), record)
    return decoded, record


def composition_frames(host, donor, method, np):
    if method == 'base':
        return host.copy(), [0.0] * 120
    if method not in ('hardcut', 'blend') or donor is None:
        raise ValueError('Invalid registered composition')
    alpha = []
    for i in range(120):
        t = Fraction(2 * i + 1, 48)
        if not Fraction(3, 2) <= t < Fraction(7, 2):
            a = Fraction(0)
        elif method == 'hardcut':
            a = Fraction(1)
        else:
            a = min(Fraction(1), (t - Fraction(3, 2)) * 4, (Fraction(7, 2) - t) * 4)
        alpha.append(float(a))
    result = np.empty_like(host)
    for i, a in enumerate(alpha):
        result[i] = np.clip(np.rint(host[i].astype(np.float64) * (1 - a)
                                  + donor[i].astype(np.float64) * a), 0, 255).astype(np.uint8)
    return result, alpha


def frame_lineage(case, construction, canonical_receipts, parent_specs):
    """Construction ancestry before lossy encoding, never a pixel probability."""
    host_id, donor_id = case['hostId'], case['donorId']
    host_ai = parent_specs[host_id]['label'] == 'ai'
    donor_ai = donor_id is not None and parent_specs[donor_id]['label'] == 'ai'
    rows = []
    for output_index, master_index in enumerate(construction['masterFrameIndices']):
        alpha = construction['alpha'][output_index]
        host_index = construction['hostCanonicalFrameIndices'][output_index]
        donor_index = construction['donorCanonicalFrameIndices'][output_index]
        rows.append({'outputIndex': output_index, 'masterIndex': master_index,
                     'hostParentId': host_id,
                     'hostSourceFrame': canonical_receipts[host_id]['sourceFrameIndices'][host_index],
                     'donorParentId': donor_id,
                     'donorSourceFrame': canonical_receipts[donor_id]['sourceFrameIndices'][donor_index]
                     if donor_id is not None and donor_index is not None else None,
                     'donorAlpha': alpha,
                     'knownAiContribution': (1 - alpha if host_ai else 0) + (alpha if donor_ai else 0)})
    return rows


def configure_opencv_threads(cv2):
    # GCD ignores positive requested limits; zero disables its parallel regions.
    cv2.setNumThreads(0)
    reported = cv2.getNumThreads()
    backends = [line.split(':', 1)[1].strip() for line in cv2.getBuildInformation().splitlines()
                if line.strip().startswith('Parallel framework:')]
    if reported != 1 or backends != ['GCD']:
        raise ValueError('Pinned OpenCV GCD runtime must report one thread after requesting zero')
    return {'opencvThreadsRequested': 0, 'opencvThreadsReported': reported,
            'opencvParallelBackend': backends[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, choices=['negative-45', 'veo-30', 'wan-30'])
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--parent-receipt', action='append', default=[])
    args = parser.parse_args()
    out = local(args.output_dir)
    if out.exists():
        raise ValueError('Build evidence is immutable; select a fresh output directory')
    plan = json.loads(SOURCE_PLAN.read_text())
    generation = json.loads(GENERATION_PLAN.read_text())
    if plan.get('frozen') is not True or generation.get('frozen') is not True:
        raise ValueError('Source and generation plans must be frozen before construction')
    import cv2
    import numpy as np
    if cv2.__version__ != '4.12.0' or np.__version__ != '2.2.6':
        raise ValueError('Exact builder OpenCV4.12.0/NumPy2.2.6 runtime required')
    thread_runtime = configure_opencv_threads(cv2)
    spec = importlib.util.spec_from_file_location('fps_lineage', LINEAGE)
    lineage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lineage)
    wrappers = {}
    for name in args.parent_receipt:
        path = local(name)
        value = json.loads(path.read_text())
        slot = value['generationSlot']
        if slot in wrappers:
            raise ValueError('Duplicate generated source slot')
        wrappers[slot] = path
    case_ids = plan['stages'][args.stage]['caseIds']
    cases = {key: plan['cases'][key] for key in case_ids}
    parent_ids = sorted(set(a for case in cases.values() for a in case['ancestors']))
    source_sha, generation_sha, protocol_sha = sha(SOURCE_PLAN), sha(GENERATION_PLAN), sha(PROTOCOL)
    parents = [parent_record(pid, plan['parents'][pid], wrappers, generation_sha, protocol_sha) for pid in parent_ids]
    out.mkdir(parents=True, exist_ok=False)
    canonical_dir = out / 'canonical'
    canonical_dir.mkdir()
    media_dir = out / 'media'
    media_dir.mkdir()
    artifact_dir = out / 'artifacts'
    artifact_dir.mkdir()
    snapshots = out / 'source'
    snapshots.mkdir()
    source_files = []
    for path in [Path(__file__), LINEAGE, SOURCE_PLAN, GENERATION_PLAN, PROTOCOL]:
        shutil.copyfile(path, snapshots / path.name)
        source_files.append({'path': str(path.relative_to(ROOT)), 'snapshot': str((snapshots / path.name).relative_to(ROOT)), 'sha256': sha(path)})
    ffmpeg_path = Path(shutil.which('ffmpeg')).resolve()
    receipt = {'status': 'building', 'stage': args.stage, 'startedAtUnix': time.time(),
               'builderSha256': sha(Path(__file__)), 'sourcePlanSha256': source_sha,
               'generationPlanSha256': generation_sha, 'evaluationProtocolSha256': protocol_sha,
               'parentReceipts': parents, 'sourceFiles': source_files, 'outputs': [],
               'runtime': {'opencv': cv2.__version__, 'numpy': np.__version__,
                           **thread_runtime,
                           'opencvDistributions': {name: importlib.metadata.version(name)
                                                   for name in importlib.metadata.packages_distributions().get('cv2', [])},
                           'ffmpegSha256': sha(ffmpeg_path),
                           'ffmpegVersion': subprocess.check_output([str(ffmpeg_path), '-version'], text=True).splitlines()[0]},
               'detectorCalls': 0}
    receipt_path = out / 'build-receipt.json'
    def persist():
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    persist()
    try:
        decoded, canonical_receipts = {}, {}
        for parent in parents:
            pid = parent['parentId']
            decoded[pid], canonical_receipts[pid] = canonical_parent(parent, plan['parents'][pid], canonical_dir, cv2, np)
        receipt['canonicalParents'] = canonical_receipts
        masters = {}
        for cid in case_ids:
            case = cases[cid]
            stem = cid.rsplit('/', 1)[0]
            opaque = hashlib.sha256((source_sha + ':' + cid).encode()).hexdigest()[:24]
            output = media_dir / (opaque + '.mp4')
            artifact = artifact_dir / opaque
            artifact.mkdir()
            if stem not in masters:
                if case['quality'] != 'master':
                    raise ValueError('Each predeclared master must precede its quality derivatives')
                pixels, alpha = composition_frames(decoded[case['hostId']], decoded.get(case['donorId']), case['composition'], np)
                command = encode_rgb(pixels, output, artifact / 'encode.log', np)
                output_probe = validate_output(output, 24, 640, 360)
                identity = list(range(120))
                construction = {'alpha': alpha, 'operation': case['composition'], 'blendSpace': 'encodedRGB',
                                'blendDtype': 'float64', 'rounding': 'np.rint ties-even',
                                'hostCanonicalSha256': canonical_receipts[case['hostId']]['canonicalSha256'],
                                'donorCanonicalSha256': canonical_receipts[case['donorId']]['canonicalSha256'] if case['donorId'] else None,
                                'preEncodeRgbFrameSha256': [hashlib.sha256(f.tobytes()).hexdigest() for f in pixels],
                                'hostCanonicalFrameIndices': identity,
                                'donorCanonicalFrameIndices': [i if a > 0 else None for i, a in enumerate(alpha)],
                                'masterFrameIndices': identity, 'encodeCommand': command}
                masters[stem] = {'path': output, 'sha256': sha(output), 'construction': construction}
            else:
                original = masters[stem]
                quality = plan['qualities'][case['quality']]
                fps = quality['fps']
                command = ['ffmpeg', '-nostats', '-loglevel', 'debug', '-nostdin', '-n',
                           '-i', str(original['path']), '-map', '0:v:0', '-an', '-vf', quality['filter'] + ',setsar=1',
                           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(quality['crf']), '-threads', '2',
                           '-pix_fmt', 'yuv420p', '-r', str(fps), '-fps_mode', 'cfr',
                           '-map_metadata', '-1', '-movflags', '+faststart', str(output)]
                process = subprocess.run(command, capture_output=True, text=True, timeout=120)
                (artifact / 'encode.log').write_text(process.stderr)
                if process.returncode:
                    raise ValueError(f'Quality encoding failed: {process.returncode}')
                mapping = lineage.parse_fps_lineage(process.stderr, 120, fps * 5)
                # The helper returns either its strict receipt or its selected input-index list.
                identity = mapping['inputIndices'] if isinstance(mapping, dict) else mapping
                if len(identity) != fps * 5 or any(i not in range(120) for i in identity):
                    raise ValueError('Actual FPS lineage differs from output dimensions')
                output_probe = validate_output(output, fps, 640 if fps == 24 else 360, 360 if fps == 24 else 202)
                construction = {**original['construction'], 'masterFrameIndices': identity,
                                'masterPath': str(original['path'].relative_to(ROOT)), 'masterSha256': original['sha256'],
                                'alpha': [original['construction']['alpha'][i] for i in identity],
                                'hostCanonicalFrameIndices': [original['construction']['hostCanonicalFrameIndices'][i] for i in identity],
                                'donorCanonicalFrameIndices': [original['construction']['donorCanonicalFrameIndices'][i] for i in identity],
                                'encodeCommand': command, 'fpsLineage': mapping,
                                'fpsDebugLogSha256': sha(artifact / 'encode.log')}
                construction['masterPreEncodeRgbFrameSha256'] = construction.pop('preEncodeRgbFrameSha256')
            write_json(artifact / 'construction.json', construction)
            lineage_path = artifact / 'frame-lineage.json'
            write_json(lineage_path, frame_lineage(case, construction, canonical_receipts, plan['parents']))
            row = {**case, 'caseId': cid, 'id': opaque, 'path': str(output.relative_to(ROOT)),
                   'sha256': sha(output), 'split': 'development', 'dataset': 'fresh-origin-shot-study',
                   'groupId': 'fresh-shot-study-linked-family',
                   'sourcePlanSha256': source_sha, 'generationPlanSha256': generation_sha,
                   'constructionReceiptPath': str((artifact / 'construction.json').relative_to(ROOT)),
                   'constructionReceiptSha256': sha(artifact / 'construction.json'),
                   'frameLineagePath': str(lineage_path.relative_to(ROOT)),
                   'frameLineageSha256': sha(lineage_path),
                   'knownAiContributionMeaning': 'Construction proportion before lossy encoding; not a decoded-pixel probability.',
                   'media': {'bytes': output.stat().st_size, 'width': output_probe['streams'][0]['width'],
                             'height': output_probe['streams'][0]['height'],
                             'frames': len(output_probe['frames']), 'fps': plan['qualities'][case['quality']]['fps'],
                             'durationSeconds': 5, 'hasAudio': False}}
            receipt['outputs'].append(row)
            persist()
            print(json.dumps({'constructed': len(receipt['outputs']), 'selected': len(case_ids), 'caseId': cid}), flush=True)
        manifest = out / 'manifest.jsonl'
        with manifest.open('x') as stream:
            for row in receipt['outputs']:
                stream.write(json.dumps(row, sort_keys=True) + '\n')
        unchanged = all(sha(local(p[key])) == p[hash_key] for p in parents
                        for key, hash_key in [('path', 'sha256'), ('originReceiptPath', 'originReceiptSha256')])
        if not unchanged:
            raise ValueError('Original parent or origin receipt changed during construction')
        if any(sha(local(item['path'])) != item['sha256']
               or sha(local(item['snapshot'])) != item['sha256'] for item in source_files):
            raise ValueError('Frozen construction source or snapshot changed during build')
        receipt.update({'status': 'completed', 'manifestPath': str(manifest.relative_to(ROOT)),
                        'manifestSha256': sha(manifest), 'completed': len(receipt['outputs']),
                        'parentFilesUnchanged': True, 'finishedAtUnix': time.time()})
        persist()
    except Exception as error:
        receipt.update({'status': 'failed', 'error': str(error), 'errorType': type(error).__name__,
                        'finishedAtUnix': time.time()})
        persist()
        raise


if __name__ == '__main__':
    main()
