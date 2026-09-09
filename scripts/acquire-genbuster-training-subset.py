#!/usr/bin/env python3
"""Plan offline; acquire only an explicitly frozen, hash-pinned training subset.

No imports perform network/media work. Three exact ZIP ranges per member, no
automatic retries, persistent byte reservations, and immutable source selection.
Publisher labels and archive identities do not establish source-family truth.
"""
import argparse
import concurrent.futures
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
REVISION = "58af00f022d8272f42de3be912e9a905bf6087d2"
URL = f"https://huggingface.co/datasets/l8cv/GenBuster-200K-mini/resolve/{REVISION}/GenBuster-200K-mini.zip"
ARCHIVE_BYTES = 5_458_325_142
CENTRAL_OFFSET = 5_456_659_705
ETAG = '"b944985d2a8d5506dfb4b377ccc992ec7fe3ca6b5763ed61b3d3565a63b5fc8c"'
ARCHIVE_LFS_SHA = "332a012eac1c0207378714d639391f991a9a200108d9c3c8f9f493a1e4c81c20"
SALT = "dinov2-temporal-v1|"
GENERATORS = ("cogvideox", "easyanimate", "hunyuanvideo", "ltxvideo")
FIXTURE = "eval/fixtures/dinov2-training-subset-v1.json"
MEDIA_DIR = "eval/media/genbuster-training-subset-v1"
RUN_DIR = "eval/runs/genbuster-training-subset-v1-acquisition"
MAX_MEMBER = 8 * 1024 * 1024
MAX_EXTRA = 4096
MAX_NETWORK = 1_500_000_000
MAX_SECONDS = 24 * 60 * 60
INPUTS = {
    "eval/sources/training-source-audit/zip-entry-census.json": "b10f999f5da2b7b12f1291bd33af89f26f3af1092999879d5b10a4a2bb668f08",
    "eval/sources/training-source-audit/zip-central-directory.bin": "8ec46b65298ca386992636a88784a4224fc6db9868d4ca62457dd94774b47d71",
    "eval/sources/genbuster-bench-zip-index.json": "6f5d936510c946502e2cd5bcf1bd1c95d0e6f37cc4e2342261e333b7c250db22",
    "eval/manifest.jsonl": "cb49a2ea8e403656c67ce6741e61abe1e06207918a5cbecb963309d61e598f67",
    "eval/transformed-manifest.jsonl": "a9a7b07a9e8513b753fb879e9e41154454d789a34c9fcf6edb7755e615db7fa1",
    "eval/control-manifest.jsonl": "cc5c3a2907a9fb8252aaf962ddf1136a708f2f66373dddc81081005804903349",
    "eval/generated-origin-manifest.jsonl": "122b79147249eab01d06e0fbd0b33955fc86eb9479d8df1697fd123c480b8b55",
    "eval/instagram-manifest.jsonl": "c628f8eeb83826015ca928f9751d41e26b2768700ac20fdbc9e9993280388d38",
    "eval/audio-control-manifest.jsonl": "0feb6960135bc9e6c2652e87961f204ca0782f3f1ea422421454b2db36337f99",
    "eval/runs/aegis-shots-v1-negative-build/manifest.jsonl": "87c02fc0b447bb0a5cc9f39ca18bda788c773db6f8e145b88bd863b54eb4dc4f",
    "eval/runs/aegis-shots-v1-negative-build/build-receipt.json": "fa899c2b5adc0e63be152c65e81e96a9260a86f9facf108623e95a0384a2b969",
    "eval/fixtures/video-generation-receipt.json": "125533f5c7d3dcf0b13cf7f61ee555312a75b4214cd50ace4756ac8da57d1498",
}
NAME = re.compile(r"train/(?:real|fake/(?:cogvideox|easyanimate|hunyuanvideo|ltxvideo))/[0-9a-f]{64}\.mp4\Z")


class IntegrityError(RuntimeError):
    """Permanent mismatch. Never retried or replaced with another member."""


class TechnicalError(RuntimeError):
    """Transport/interruption failure eligible for one explicit retry."""


def require(condition, message):
    if not condition:
        raise IntegrityError(message)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def safe_path(root, relative):
    rel = Path(relative)
    require(not rel.is_absolute() and ".." not in rel.parts, "Unsafe output path")
    p = root
    for part in rel.parts:
        p = p / part
        require(not p.is_symlink(), "Symlink in acquisition path")
    require(p.resolve().is_relative_to(root.resolve()), "Path escaped acquisition root")
    return p


def read_file(path, maximum=20_000_000):
    require(not path.is_symlink(), "Refusing symlink read")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
        body = f.read(maximum + 1)
    require(len(body) <= maximum, "File exceeds read bound")
    return body


def write_new(path, body):
    """Publish only a new file; never replace an existing media/artifact."""
    require(not path.is_symlink(), "Refusing symlink output")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())


def atomic_state(path, value):
    """Only our mutable receipt state uses replacement; every attempt is retained."""
    require(not path.is_symlink(), "Refusing symlink state")
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        write_new(temp, json_bytes(value))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def validate_entry(entry):
    require(isinstance(entry, dict) and NAME.fullmatch(entry.get("name", "")), "Unexpected ZIP member path")
    for key in ("flags", "method", "compressedBytes", "uncompressedBytes", "localHeaderOffset"):
        require(type(entry.get(key)) is int, "Invalid ZIP integer")
    require(entry["flags"] & ~0x806 == 0, "Encrypted/data-descriptor/unsupported ZIP flags")
    require(entry["method"] in (0, 8), "Unsupported ZIP compression")
    require(entry["method"] == 8 or not entry["flags"] & 6, "Deflate flags on stored member")
    require(1 <= entry["compressedBytes"] <= MAX_MEMBER, "Compressed member exceeds cap")
    require(1 <= entry["uncompressedBytes"] <= MAX_MEMBER, "Uncompressed member exceeds cap")
    require(re.fullmatch(r"[0-9a-f]{8}", entry.get("crc32", "")), "Invalid CRC32 metadata")
    require(0 <= entry["localHeaderOffset"] < CENTRAL_OFFSET, "Invalid local-header offset")


def select_entries(census, benchmark, registered):
    """Pure metadata selection, used identically for planning and verification."""
    offsets = sorted(e["localHeaderOffset"] for e in census)
    require(len(offsets) == len(set(offsets)), "Duplicate local-header offsets")
    boundaries = dict(zip(offsets, offsets[1:] + [CENTRAL_OFFSET]))
    bench_files = [e for e in benchmark["entries"] if e["path"].endswith(".mp4")]
    names = {Path(e["path"]).name for e in bench_files}
    names |= {Path(e.get("archiveMember", "")).name for e in registered}
    names |= {e["sha256"] + ".mp4" for e in registered}
    crc_sizes = {(e["crc"], e["size"]) for e in bench_files}
    buckets = {k: [] for k in ("real", *GENERATORS)}
    excluded = []
    seen = set()
    for entry in census:
        if entry["name"].endswith("/"):
            continue
        validate_entry(entry)
        require(entry["name"] not in seen, "Duplicate member name")
        seen.add(entry["name"])
        if Path(entry["name"]).name in names or (int(entry["crc32"], 16), entry["uncompressedBytes"]) in crc_sizes:
            excluded.append(entry["name"])
            continue
        bucket = "real" if entry["name"].startswith("train/real/") else entry["name"].split("/")[2]
        buckets[bucket].append(entry)
    rows = []
    # Train first, then development; within each split real then fixed generator order.
    for split in ("train", "internal_development"):
        for bucket in buckets:
            training_count, dev_count = (1024, 128) if bucket == "real" else (256, 32)
            ranked = sorted(buckets[bucket], key=lambda e: sha((SALT + e["name"]).encode()))
            require(len(ranked) >= training_count + dev_count, "Insufficient eligible fixed bucket")
            chosen = ranked[:training_count] if split == "train" else ranked[training_count:training_count + dev_count]
            for entry in chosen:
                opaque = sha((REVISION + "|" + entry["name"]).encode())
                rows.append({
                    "id": opaque, "parentId": opaque, "groupId": "genbuster-mini-entry:" + opaque,
                    "split": split, "label": "real" if bucket == "real" else "ai",
                    "generator": None if bucket == "real" else bucket,
                    "archiveMember": entry["name"], "selectionRankSha256": sha((SALT + entry["name"]).encode()),
                    "path": MEDIA_DIR + "/" + opaque + ".mp4", "zip": entry,
                    "entryBoundary": boundaries[entry["localHeaderOffset"]],
                })
    require(len({r["id"] for r in rows}) == len(rows), "Selection identity collision")
    return rows, excluded


def collect_media_hashes(value):
    found = set()
    if isinstance(value, list):
        for item in value:
            found |= collect_media_hashes(item)
    elif isinstance(value, dict):
        if isinstance(value.get("path"), str) and value["path"].lower().endswith((".mp4", ".mov", ".mkv")):
            digest = value.get("sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                found.add(digest)
        # Existing CGI manifests also identify the preserved trailer this way.
        digest = value.get("cgiSourceSha256")
        if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            found.add(digest)
        for item in value.values():
            found |= collect_media_hashes(item)
    return found


def make_plan(root=ROOT):
    inputs = {}
    for name, expected in INPUTS.items():
        body = read_file(safe_path(root, name))
        require(sha(body) == expected, "Pinned selection input changed: " + name)
        inputs[name] = body
    census = json.loads(inputs[next(iter(INPUTS))])
    benchmark = json.loads(inputs["eval/sources/genbuster-bench-zip-index.json"])
    registered = [json.loads(line) for line in inputs["eval/manifest.jsonl"].splitlines()]
    require(len(registered) == 230, "Registered benchmark count changed")
    rows, excluded = select_entries(census, benchmark, registered)
    excluded_hashes = set()
    for name, body in inputs.items():
        if name.endswith(".jsonl"):
            value = [json.loads(line) for line in body.splitlines()]
        elif name.endswith(".json") and name not in (next(iter(INPUTS)), "eval/sources/genbuster-bench-zip-index.json"):
            value = json.loads(body)
        else:
            continue
        excluded_hashes |= collect_media_hashes(value)
    compressed = sum(r["zip"]["compressedBytes"] for r in rows)
    names = sum(len(r["archiveMember"].encode("ascii")) for r in rows)
    fixed_headers = 30 * len(rows)
    max_extra = MAX_EXTRA * len(rows)
    return {
        "schemaVersion": 1, "studyId": "dinov2-temporal-v1", "frozen": False, "frozenAt": None,
        "acquisitionScriptSha256": sha(read_file(Path(__file__))), "selectionSalt": SALT,
        "dataset": "GenBuster-200K-mini", "revision": REVISION, "sourceUrl": URL,
        "archiveBytes": ARCHIVE_BYTES, "archivePublishedLfsSha256": ARCHIVE_LFS_SHA,
        "wholeArchiveHashVerified": False, "expectedResponseETag": ETAG,
        "inputSha256": INPUTS, "excludedArchiveMembers": excluded,
        "excludedKnownMediaSha256": sorted(excluded_hashes),
        "labelBasis": "weak-publisher-folder-label", "license": "MIT (publisher dataset-card declaration)",
        "limitations": ["Archive-entry/file identities are not source, creator, prompt, or reference families.",
                        "No verified CGI/mixed interval supervision; generated bucket/version truth is publisher asserted.",
                        "No benchmark basename or CRC-size overlap; actual hashes additionally checked against the 230 registered originals.",
                        "No semantic or re-encoding independence claim; all benchmark 230 remain outside this training allocation."],
        "counts": {"train": {"real": 1024, "ai": 1024, "aiPerGenerator": 256},
                   "internal_development": {"real": 128, "ai": 128, "aiPerGenerator": 32}, "total": len(rows)},
        "limits": {"maxCompressedMemberBytes": MAX_MEMBER, "maxUncompressedMemberBytes": MAX_MEMBER,
                   "maxLocalExtraBytes": MAX_EXTRA, "maxNetworkReservationBytes": MAX_NETWORK,
                   "maxWorkers": 4, "maxMemberAttempts": 2, "automaticRetries": 0,
                   "socketTimeoutSeconds": 20, "rangeDeadlineSeconds": 60,
                   "rangeMaximumBlockingGraceSeconds": 20, "runDeadlineSeconds": MAX_SECONDS,
                   "maxRedirectsPerRange": 3, "ffprobeTimeoutSeconds": 30, "maxVideoDurationSeconds": 120,
                   "maxVideoDimension": 4096},
        "bytes": {"compressedMedia": compressed,
                  "uncompressedMedia": sum(r["zip"]["uncompressedBytes"] for r in rows),
                  "fixedLocalHeaders": fixed_headers, "localFilenames": names,
                  "localExtraMaximum": max_extra,
                  "firstAttemptMaximumRangeBodies": compressed + fixed_headers + names + max_extra,
                  "firstAttemptMaximumReservationsIncludingOverflowGuards": compressed + fixed_headers + names + max_extra + 3 * len(rows),
                  "firstAttemptRanges": 3 * len(rows),
                  "budgetMeaning": "Requested range bodies plus one-byte overflow guard each, including failed reservations and one explicit technical retry when budget remains; excludes HTTP/TLS overhead."},
        "mediaDirectory": MEDIA_DIR, "receiptDirectory": RUN_DIR, "entries": rows,
    }


def load_frozen(path, expected_sha, root=ROOT):
    body = read_file(path, 4_000_000)
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha or "") and sha(body) == expected_sha, "Fixture SHA-256 does not match explicit pin")
    plan = json.loads(body)
    require(plan.get("frozen") is True and isinstance(plan.get("frozenAt"), str), "Subset is not frozen for acquisition")
    stamp = datetime.datetime.fromisoformat(plan["frozenAt"])
    require(stamp.tzinfo is not None, "Freeze timestamp must include timezone")
    normalized = dict(plan, frozen=False, frozenAt=None)
    require(normalized == make_plan(root), "Frozen subset differs from deterministic pinned plan")
    return plan


def valid_redirect(url):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    require(p.scheme == "https" and not p.username and not p.password and p.port in (None, 443), "Unsafe range redirect")
    require(host == "huggingface.co" or host.endswith(".huggingface.co") or host == "hf.co" or host.endswith(".hf.co"), "Range redirect outside official hosting domains")
    require(len(url) <= 16_384, "Oversized redirect URL")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        # Do not read potentially unbounded redirect bodies or persist signed URLs.
        fp.close()
        require("Location" in headers, "Redirect has no location")
        url = urllib.parse.urljoin(req.full_url, headers["Location"])
        valid_redirect(url)
        count = getattr(req, "range_redirect_count", 0) + 1
        require(count <= 3, "Too many range redirects")
        new = urllib.request.Request(url, headers={"Range": req.get_header("Range"), "Accept-Encoding": "identity"})
        new.range_redirect_count = count
        new.range_deadline = req.range_deadline
        remaining = new.range_deadline - time.monotonic()
        if remaining <= 0:
            raise TechnicalError("Range redirect deadline exceeded")
        return self.parent.open(new, timeout=min(20, remaining))

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def fetch_range(start, count, opener=None):
    require(type(start) is int and type(count) is int and start >= 0 and count > 0 and start + count <= ARCHIVE_BYTES, "Invalid HTTP range")
    require(count <= MAX_MEMBER + MAX_EXTRA + 256, "HTTP range exceeds cap")
    request = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{start + count - 1}", "Accept-Encoding": "identity"})
    deadline = time.monotonic() + 60
    request.range_deadline = deadline
    opener = opener or urllib.request.build_opener(SafeRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            require(response.status == 206, "Server did not honor exact range")
            require(response.headers.get("Content-Range") == f"bytes {start}-{start + count - 1}/{ARCHIVE_BYTES}", "Content-Range mismatch")
            require(response.headers.get("Content-Length") == str(count), "Content-Length mismatch")
            require(response.headers.get("Content-Encoding", "identity") == "identity", "Encoded range response")
            require(response.headers.get("ETag") == ETAG, "Pinned archive response ETag changed")
            chunks, received = [], 0
            while received <= count:
                if time.monotonic() >= deadline:
                    raise TechnicalError("Range wall-clock deadline exceeded")
                part = response.read1(min(65536, count + 1 - received))
                if not part:
                    break
                received += len(part)
                chunks.append(part)
            body = b"".join(chunks)
            require(len(body) <= count, "Oversized range body")
            if len(body) != count:
                raise TechnicalError("Incomplete range body")
            return body
    except urllib.error.HTTPError as error:
        if error.code == 429 or 500 <= error.code <= 599:
            raise TechnicalError(f"HTTP transport status {error.code}") from None
        raise IntegrityError(f"HTTP status {error.code}; no retry") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        # Error class only: exceptions can contain temporary signed CDN URLs.
        raise TechnicalError("Range transport failure: " + type(error).__name__) from None


def parse_header(header, entry):
    validate_entry(entry)
    require(len(header) == 30, "Invalid local-header length")
    signature, version, flags, method, _, _, crc, compressed, size, name_len, extra_len = struct.unpack("<4s5H3I2H", header)
    require(signature == b"PK\x03\x04" and 10 <= version <= 45 and (method != 8 or version >= 20), "Invalid local ZIP signature/version")
    require(flags == entry["flags"] and method == entry["method"], "Local flags/method differ from central directory")
    require(crc == int(entry["crc32"], 16), "Local CRC differs from central directory")
    require(name_len == len(entry["name"].encode("ascii")), "Local filename length mismatch")
    require(extra_len <= MAX_EXTRA, "Local ZIP extra exceeds cap")
    return {"compressed": compressed, "size": size, "nameBytes": name_len, "extraBytes": extra_len}


def verify_local_fields(body, header, entry):
    n = header["nameBytes"]
    require(len(body) == n + header["extraBytes"], "Local name/extra length mismatch")
    require(body[:n] == entry["name"].encode("ascii"), "Local member name differs from central directory")
    extra, pos, fields = body[n:], 0, {}
    while pos < len(extra):
        require(pos + 4 <= len(extra), "Truncated ZIP extra header")
        tag, length = struct.unpack_from("<HH", extra, pos)
        pos += 4
        require(pos + length <= len(extra) and tag not in fields, "Truncated/duplicate ZIP extra field")
        fields[tag] = extra[pos:pos + length]
        pos += length
    size, compressed = header["size"], header["compressed"]
    if size == 0xFFFFFFFF or compressed == 0xFFFFFFFF:
        z64 = fields.get(1, b"")
        required = 8 * ((size == 0xFFFFFFFF) + (compressed == 0xFFFFFFFF))
        require(len(z64) == required, "Invalid local ZIP64 sizes")
        pos = 0
        if size == 0xFFFFFFFF:
            size = struct.unpack_from("<Q", z64, pos)[0]
            pos += 8
        if compressed == 0xFFFFFFFF:
            compressed = struct.unpack_from("<Q", z64, pos)[0]
    else:
        require(1 not in fields, "Unexpected local ZIP64 sizes")
    require(size == entry["uncompressedBytes"] and compressed == entry["compressedBytes"], "Local sizes differ from central directory")


def decode_member(payload, entry):
    require(len(payload) == entry["compressedBytes"], "Compressed payload size mismatch")
    try:
        if entry["method"] == 8:
            inflater = zlib.decompressobj(-15)
            body = inflater.decompress(payload, entry["uncompressedBytes"] + 1)
            require(inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail, "Incomplete/trailing/overlong deflate stream")
        elif entry["method"] == 0:
            body = payload
        else:
            raise IntegrityError("Unsupported member compression")
    except zlib.error:
        raise IntegrityError("Invalid deflate stream") from None
    require(len(body) == entry["uncompressedBytes"], "Uncompressed payload size mismatch")
    require(zlib.crc32(body) == int(entry["crc32"], 16), "Uncompressed CRC32 mismatch")
    return body


def download_member(row, fetch):
    entry = row["zip"]
    offset = entry["localHeaderOffset"]
    header_bytes = fetch(offset, 30, "localHeader")
    header = parse_header(header_bytes, entry)
    tail_count = header["nameBytes"] + header["extraBytes"]
    payload_offset = offset + 30 + tail_count
    require(payload_offset + entry["compressedBytes"] <= row["entryBoundary"] <= CENTRAL_OFFSET, "Member crosses next entry/central directory")
    local_fields = fetch(offset + 30, tail_count, "localNameAndExtra")
    verify_local_fields(local_fields, header, entry)
    payload = fetch(payload_offset, entry["compressedBytes"], "compressedMedia")
    return decode_member(payload, entry), {"localHeaderSha256": sha(header_bytes), "localFieldsSha256": sha(local_fields),
                                         "compressedSha256": sha(payload), "payloadOffset": payload_offset,
                                         "localExtraBytes": header["extraBytes"]}


class Budget:
    """One process lock outside; thread lock + fsync before every network request."""
    def __init__(self, path, maximum=MAX_NETWORK):
        self.path, self.maximum, self.lock = path, maximum, threading.Lock()
        self.events = []
        if path.exists():
            body = read_file(path, 30_000_000)
            require(not body or body.endswith(b"\n"), "Interrupted byte journal; explicit audit required")
            self.events = [json.loads(line) for line in body.splitlines()]
        self.reserved = 0
        for i, event in enumerate(self.events):
            require(event["sequence"] == i and event["kind"] in ("reserve", "received"), "Invalid byte journal")
            if event["kind"] == "reserve":
                require(type(event["reservationBytes"]) is int and event["reservationBytes"] > 0, "Invalid reservation")
                self.reserved += event["reservationBytes"]
        require(self.reserved <= maximum, "Previously reserved network budget exceeded")

    def append(self, event):
        event = dict(event, sequence=len(self.events), at=now())
        line = (json.dumps(event, sort_keys=True) + "\n").encode()
        with os.fdopen(os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600), "ab") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        self.events.append(event)

    def fetch(self, row_id, attempt, start, count, purpose, transport=fetch_range):
        with self.lock:
            require(self.reserved + count + 1 <= self.maximum, "Persistent network reservation budget exhausted")
            self.append({"kind": "reserve", "id": row_id, "attempt": attempt, "purpose": purpose,
                         "start": start, "count": count, "reservationBytes": count + 1})
            self.reserved += count + 1
        body = transport(start, count)
        with self.lock:
            self.append({"kind": "received", "id": row_id, "attempt": attempt, "purpose": purpose,
                         "start": start, "count": count, "receivedBytes": len(body), "sha256": sha(body)})
        return body


def probe_media(path):
    binary = shutil.which("ffprobe")
    require(binary is not None, "ffprobe is unavailable")
    try:
        result = subprocess.run([binary, "-v", "error", "-threads", "1", "-protocol_whitelist", "file",
                                 "-show_entries", "format=duration,format_name:stream=codec_type,codec_name,width,height,avg_frame_rate,duration",
                                 "-of", "json", str(path)], capture_output=True, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        raise IntegrityError("ffprobe timed out; no replacement selected") from None
    require(result.returncode == 0 and len(result.stdout) <= 65536, "ffprobe failed or exceeded output bound")
    data = json.loads(result.stdout)
    require("mp4" in data.get("format", {}).get("format_name", "").split(","), "Member is not an MP4 container")
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    require(len(videos) == 1, "Expected exactly one video stream")
    video = videos[0]
    duration = float(data.get("format", {}).get("duration", 0))
    require(math.isfinite(duration) and 0 < duration <= 120, "Video duration outside acquisition bound")
    require(all(type(video.get(k)) is int and 0 < video[k] <= 4096 for k in ("width", "height")), "Video dimensions outside acquisition bound")
    rate = video.get("avg_frame_rate", "0/0").split("/")
    require(len(rate) == 2 and float(rate[1]) > 0 and 0 < float(rate[0]) / float(rate[1]) <= 240, "Invalid frame rate")
    return {"durationSeconds": duration, "width": video["width"], "height": video["height"],
            "frameRate": video["avg_frame_rate"], "codec": video.get("codec_name"),
            "hasAudio": any(s.get("codec_type") == "audio" for s in data["streams"]),
            "validation": "ffprobe metadata; full decode and source authentication not established"}


def verify_cached(path, row, receipt, excluded_hashes):
    body = read_file(path, MAX_MEMBER)
    require(len(body) == row["zip"]["uncompressedBytes"] and zlib.crc32(body) == int(row["zip"]["crc32"], 16), "Cached media size/CRC changed")
    digest = sha(body)
    require(digest == receipt["sha256"] and digest not in excluded_hashes, "Cached content hash mismatch/benchmark overlap")
    require(receipt.get("bytes") == len(body) and isinstance(receipt.get("media"), dict) and isinstance(receipt.get("zip"), dict), "Incomplete cached acquisition receipt")
    return digest


def acquire_one(root, row, budget, fixture_sha, excluded_hashes, retry_failed=False, transport=fetch_range, probe=probe_media):
    target = safe_path(root, row["path"])
    state_path = safe_path(root, RUN_DIR + "/members/" + row["id"] + ".json")
    state = {"id": row["id"], "fixtureSha256": fixture_sha, "archiveMember": row["archiveMember"], "attempts": []}
    if state_path.exists():
        state = json.loads(read_file(state_path, 128_000))
        require(state["id"] == row["id"] and state["fixtureSha256"] == fixture_sha and state["archiveMember"] == row["archiveMember"], "Resume receipt identity mismatch")
    attempts = state["attempts"]
    if attempts and attempts[-1]["status"] == "complete":
        require(target.exists(), "Complete receipt has missing media")
        verify_cached(target, row, attempts[-1], excluded_hashes)
        return attempts[-1]
    require(not target.exists(), "Unreceipted media exists; explicit audit required")
    if attempts:
        require(retry_failed and len(attempts) == 1 and attempts[-1]["status"] in ("technicalFailure", "started"), "Failed member requires one explicit technical retry; no replacement")
    require(len(attempts) < 2, "Member retry limit reached")
    attempt = {"number": len(attempts) + 1, "status": "started", "startedAt": now()}
    attempts.append(attempt)
    atomic_state(state_path, state)
    temp = target.with_name("." + row["id"] + "." + uuid.uuid4().hex + ".part")
    try:
        body, zip_receipt = download_member(row, lambda start, count, purpose: budget.fetch(row["id"], attempt["number"], start, count, purpose, transport))
        digest = sha(body)
        require(digest not in excluded_hashes, "Actual content overlaps registered benchmark; no replacement")
        write_new(temp, body)
        media = probe(temp)
        # Link is atomic and fails if target exists. No rename can overwrite media.
        os.link(temp, target, follow_symlinks=False)
        attempt.update(status="complete", finishedAt=now(), sha256=digest, bytes=len(body), media=media,
                       zip=zip_receipt, publisherBasenameEqualsContentSha256=Path(row["archiveMember"]).stem == digest)
        atomic_state(state_path, state)
        return attempt
    except Exception as error:
        attempt.update(status="technicalFailure" if isinstance(error, TechnicalError) else "rejected", finishedAt=now(),
                       error=str(error) if isinstance(error, (TechnicalError, IntegrityError)) else type(error).__name__)
        atomic_state(state_path, state)
        raise
    finally:
        temp.unlink(missing_ok=True)


def verify_live_bindings(plan, fixture_sha, root):
    require(sha(read_file(safe_path(root, FIXTURE), 4_000_000)) == fixture_sha, "Fixture changed during acquisition")
    require(sha(read_file(Path(__file__))) == plan["acquisitionScriptSha256"], "Acquisition script changed")
    for path, expected in plan["inputSha256"].items():
        require(sha(read_file(safe_path(root, path))) == expected, "Pinned acquisition input changed")


def run_acquisition(plan, fixture_sha, workers=1, retry_failed=False, root=ROOT):
    require(1 <= workers <= 4, "Worker bound exceeded")
    verify_live_bindings(plan, fixture_sha, root)
    for relative in (MEDIA_DIR, RUN_DIR, RUN_DIR + "/members"):
        safe_path(root, relative).mkdir(parents=True, exist_ok=True)
    lock_path = safe_path(root, RUN_DIR + "/acquisition.lock")
    with os.fdopen(os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "wb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding = {"fixtureSha256": fixture_sha, "scriptSha256": sha(read_file(Path(__file__))), "sourceUrl": URL, "archiveBytes": ARCHIVE_BYTES}
        binding_path = safe_path(root, RUN_DIR + "/binding.json")
        if binding_path.exists():
            require(json.loads(read_file(binding_path)) == binding, "Acquisition resume binding changed")
        else:
            write_new(binding_path, json_bytes(binding))
        budget = Budget(safe_path(root, RUN_DIR + "/range-journal.jsonl"))
        excluded_hashes = set(plan["excludedKnownMediaSha256"])
        receipts, content_ids = {}, {}
        started = time.monotonic()
        error = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for begin in range(0, len(plan["entries"]), workers):
                require(time.monotonic() - started < MAX_SECONDS, "Acquisition run deadline exceeded")
                futures = {pool.submit(acquire_one, root, row, budget, fixture_sha, excluded_hashes, retry_failed): row
                           for row in plan["entries"][begin:begin + workers]}
                for future in concurrent.futures.as_completed(futures):
                    row = futures[future]
                    try:
                        receipt = future.result()
                        require(receipt["sha256"] not in content_ids, "Duplicate actual content within fixed selection; no replacement")
                        content_ids[receipt["sha256"]] = row["id"]
                        receipts[row["id"]] = receipt
                    except Exception as caught:
                        error = caught
                print(json.dumps({"verifiedComplete": len(receipts), "of": len(plan["entries"]), "reservedRangeBytes": budget.reserved}), flush=True)
                if error:
                    break
        summary = dict(binding, finishedAt=now(), complete=error is None and len(receipts) == len(plan["entries"]),
                       verifiedComplete=len(receipts), selected=len(plan["entries"]), reservedRangeBytes=budget.reserved,
                       elapsedSeconds=time.monotonic() - started, workers=workers, explicitTechnicalRetry=retry_failed,
                       error=None if error is None else (str(error) if isinstance(error, (IntegrityError, TechnicalError)) else type(error).__name__))
        summary_path = safe_path(root, RUN_DIR + "/run-" + uuid.uuid4().hex + ".json")
        write_new(summary_path, json_bytes(summary))
        if error:
            raise error
        require(summary["complete"], "Incomplete fixed cohort")
        verify_live_bindings(plan, fixture_sha, root)
        rows = []
        for row in plan["entries"]:
            r = receipts[row["id"]]
            rows.append(dict(row, sha256=r["sha256"], bytes=r["bytes"], mimeType="video/mp4", dataset=plan["dataset"],
                             transformation="original", platform="dataset", media=r["media"],
                             groundTruth={"basis": plan["labelBasis"], "labelPath": row["archiveMember"], "limitation": plan["limitations"][0]},
                             license=plan["license"], sourceUrl="https://huggingface.co/datasets/l8cv/GenBuster-200K-mini",
                             acquisitionFixtureSha256=fixture_sha))
        output = b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows)
        manifest = safe_path(root, RUN_DIR + "/manifest.jsonl")
        if manifest.exists():
            require(read_file(manifest) == output, "Completed acquisition manifest changed")
        else:
            write_new(manifest, output)
        completion = dict(binding, schemaVersion=1, complete=True, records=len(rows),
                          counts=plan["counts"], uniqueContentHashes=len(content_ids),
                          excludedKnownMediaHashes=len(excluded_hashes),
                          actualUncompressedBytes=sum(r["bytes"] for r in rows),
                          manifestPath=str(manifest.relative_to(root)), manifestSha256=sha(output))
        completion_path = safe_path(root, RUN_DIR + "/completion.json")
        if completion_path.exists():
            require(json.loads(read_file(completion_path)) == completion, "Completed acquisition receipt changed")
        else:
            write_new(completion_path, json_bytes(completion))
        print(json.dumps(dict(summary, manifest=str(manifest.relative_to(root)), manifestSha256=sha(output))), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="Offline only; create proposed fixture, never overwrite a different one")
    acquire = sub.add_parser("acquire", help="Requires frozen fixture, exact SHA and matching source/script pins")
    acquire.add_argument("--expected-fixture-sha256", required=True)
    acquire.add_argument("--workers", type=int, default=1, choices=range(1, 5))
    acquire.add_argument("--retry-failed-once", action="store_true", help="Resume interrupted/technical failures only, once total per member, within existing byte budget")
    args = parser.parse_args()
    fixture = safe_path(ROOT, FIXTURE)
    if args.command == "plan":
        plan = make_plan()
        body = json_bytes(plan)
        fixture.parent.mkdir(parents=True, exist_ok=True)
        if fixture.exists():
            require(read_file(fixture, 4_000_000) == body, "Fixture already exists with different content; never overwrite a selection")
        else:
            write_new(fixture, body)
        print(json.dumps({"fixture": FIXTURE, "sha256": sha(body), "frozen": False, "counts": plan["counts"], "bytes": plan["bytes"]}))
    else:
        plan = load_frozen(fixture, args.expected_fixture_sha256)
        run_acquisition(plan, args.expected_fixture_sha256, args.workers, args.retry_failed_once)


if __name__ == "__main__":
    main()
