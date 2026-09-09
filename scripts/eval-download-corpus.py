#!/usr/bin/env python3
"""Download bounded, labelled members of the public GenBuster benchmark.

Reads individual ZIP members with HTTP ranges; never downloads the entire archive.
Dataset labels are evidence supplied by the dataset authors, not model predictions.
"""
import argparse
import concurrent.futures
import hashlib
import io
import json
import pathlib
import struct
import subprocess
import time
import urllib.request
import zlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX = ROOT / "eval/sources/genbuster-bench-zip-index.json"
ARCHIVE_URL = "https://huggingface.co/datasets/l8cv/GenBuster-Bench/resolve/68e41ab55726013f1c7455980180114302196c23/GenBuster-Bench.zip"
ARCHIVE_BYTES = 2_184_869_288


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fetch_range(url, start, count):
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{start+count-1}"})
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status != 206:
                    raise RuntimeError("Server did not honor bounded range request")
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {start}-"):
                    raise RuntimeError("Unexpected byte range returned")
                value = response.read(count + 1)
                if len(value) != count:
                    raise RuntimeError("Incomplete ZIP member")
                return value
        except Exception:
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


def load_index():
    if INDEX.exists():
        return json.loads(INDEX.read_text())

    class RemoteZip(io.RawIOBase):
        def __init__(self):
            self.pos = 0
        def seekable(self):
            return True
        def tell(self):
            return self.pos
        def seek(self, offset, whence=0):
            self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else ARCHIVE_BYTES + offset
            return self.pos
        def read(self, count=-1):
            count = ARCHIVE_BYTES - self.pos if count < 0 else min(count, ARCHIVE_BYTES - self.pos)
            if count <= 0:
                return b""
            if count > 20_000_000:
                raise RuntimeError("ZIP directory unexpectedly large")
            body = fetch_range(ARCHIVE_URL, self.pos, count)
            self.pos += len(body)
            return body

    with zipfile.ZipFile(RemoteZip()) as archive:
        entries = [{"path": x.filename, "size": x.file_size, "compressed": x.compress_size,
                    "offset": x.header_offset, "method": x.compress_type, "crc": x.CRC} for x in archive.infolist()]
    value = {"url": ARCHIVE_URL, "archiveBytes": ARCHIVE_BYTES, "entries": entries}
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(value, indent=2) + "\n")
    return value


def download_member(index, member):
    # Header first, then exactly the member's compressed bytes. Filenames are
    # inspected as metadata only and never extracted into filesystem paths.
    header = fetch_range(index["url"], member["offset"], 30)
    fields = struct.unpack("<4s5H3I2H", header)
    if fields[0] != b"PK\x03\x04":
        raise RuntimeError("Invalid ZIP local header")
    offset = member["offset"] + 30 + fields[-2] + fields[-1]
    compressed = fetch_range(index["url"], offset, member["compressed"])
    if member["method"] == 8:
        body = zlib.decompress(compressed, -15)
    elif member["method"] == 0:
        body = compressed
    else:
        raise RuntimeError("Unsupported ZIP method")
    if len(body) != member["size"] or zlib.crc32(body) != member["crc"]:
        raise RuntimeError("ZIP integrity verification failed")
    return body


def probe(path):
    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ]))
    stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    return {"durationSeconds": float(data["format"]["duration"]), "width": stream["width"],
            "height": stream["height"], "frameRate": stream.get("avg_frame_rate"),
            "bytes": path.stat().st_size, "hasAudio": any(s["codec_type"] == "audio" for s in data["streams"])}


def split_for(group):
    bucket = int(digest("slop-eval-v1:" + group)[:8], 16) % 10
    return "development" if bucket < 4 else "calibration" if bucket < 6 else "holdout"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-generator", type=int, default=2)
    parser.add_argument("--real", type=int, default=12)
    parser.add_argument("--max-bytes", type=int, default=1_800_000_000)
    parser.add_argument("--max-clip-bytes", type=int, default=20_000_000)
    parser.add_argument("--manifest", default="eval/manifest.jsonl")
    parser.add_argument("--smoke", action="store_true", help="Assign quick smoke corpus entirely to development")
    args = parser.parse_args()
    smoke_path = ROOT / "eval/smoke-manifest.jsonl"
    smoke_groups = {r["groupId"] for r in map(json.loads, smoke_path.read_text().splitlines())} if smoke_path.exists() else set()
    index = load_index()
    buckets = {}
    for member in index["entries"]:
        name = member["path"]
        if not name.endswith(".mp4") or member["size"] > args.max_clip_bytes:
            continue
        parts = name.split("/")
        if "real" in parts:
            key = "real"
        elif "fake" in parts:
            key = parts[parts.index("fake") + 1]
        else:
            continue
        buckets.setdefault(key, []).append(member)
    selected = []
    for key, members in sorted(buckets.items()):
        count = args.real if key == "real" else args.per_generator
        for member in sorted(members, key=lambda x: digest("selection-v1:" + x["path"]))[:count]:
            selected.append((key, member))
    if sum(member["size"] for _, member in selected) > args.max_bytes:
        raise RuntimeError("Requested corpus exceeds disk budget")
    (ROOT / "eval/media").mkdir(parents=True, exist_ok=True)

    def process(item):
        key, member = item
        opaque_id = digest("genbuster-bench:" + member["path"])[:24]
        relative_path = f"eval/media/{opaque_id}.mp4"
        path = ROOT / relative_path
        if not path.exists():
            body = download_member(index, member)
            path.write_bytes(body)
        # Same source filename is grouped across generator directories. This is
        # conservative for identifiers shared by generated counterparts.
        source_id = pathlib.PurePosixPath(member["path"]).stem
        group = "genbuster:" + source_id
        return {"id": opaque_id, "path": relative_path, "mimeType": "video/mp4",
                "label": "real" if key == "real" else "ai", "dataset": "GenBuster-Bench",
                "generator": None if key == "real" else key, "groupId": group,
                "split": "development" if args.smoke or group in smoke_groups else split_for(group), "transformation": "original", "platform": "dataset",
                "sourceUrl": "https://huggingface.co/datasets/l8cv/GenBuster-Bench",
                "downloadUrl": index["url"], "archiveMember": member["path"],
                "license": "MIT (dataset card)",
                "groundTruth": {"basis": "dataset-author-label", "evidenceUrl": "https://github.com/l8cv/BusterX",
                                "labelPath": member["path"],
                                "limitation": "Public benchmark label; original camera source and creator IDs are not supplied per clip. Not independently authenticated."},
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "media": probe(path)}

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for row in pool.map(process, selected):
            rows.append(row)
            print(json.dumps({"downloaded": len(rows), "of": len(selected), "id": row["id"]}), flush=True)
    output = ROOT / args.manifest
    output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in sorted(rows, key=lambda x: x["id"])))
    print(json.dumps({"manifest": str(output), "clips": len(rows), "bytes": sum(r["media"]["bytes"] for r in rows),
                      "groups": len(set(r["groupId"] for r in rows)), "buckets": {k: len(v) for k, v in buckets.items()}}))


if __name__ == "__main__":
    main()
