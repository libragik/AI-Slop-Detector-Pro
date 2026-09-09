#!/usr/bin/env python3
"""Acquire exactly three already audited public camera-source encodes.

This only downloads and probes media. It never calls a detector, chooses a
performance-based crop, or changes an evaluation split.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
HEADS = ROOT / "eval/sources/independent-camera-access-heads.json"
OUTPUT = ROOT / "eval/sources/camera-origin-acquisition.json"
MEDIA = ROOT / "eval/media/camera-origins"
SELECTED = {
    "nasa-iss-20110917",
    "noaa-index-2010",
    "usgs-mlk-20050502-original-agency-download",
}


def acquire(row):
    record = dict(row)
    record["startedAt"] = datetime.now(timezone.utc).isoformat()
    temporary = MEDIA / (row["id"] + ".part")
    expected = int(row["contentLength"])
    try:
        if not 0 < expected <= 30_000_000:
            raise ValueError("Source exceeds the preselected per-file bound")
        request = urllib.request.Request(row["url"], headers={"User-Agent": "Camera-origin-evaluation/1.0"})
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 200:
                raise ValueError("Expected full successful download")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != expected:
                raise ValueError("Source byte length changed since selection")
            record["download"] = {
                "finalUrl": response.url, "status": response.status,
                "contentType": response.headers.get("Content-Type"),
                "contentLength": length, "etag": response.headers.get("ETag"),
                "lastModified": response.headers.get("Last-Modified"),
            }
            with temporary.open("xb") as stream:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > expected:
                        raise ValueError("Download exceeded preselected source length")
                    digest.update(chunk)
                    stream.write(chunk)
        if total != expected:
            raise ValueError("Incomplete source download")
        media_hash = digest.hexdigest()
        final = MEDIA / (media_hash[:24] + ".mp4")
        if final.exists():
            raise ValueError("Refuse to overwrite a prior source acquisition")
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_format", "-show_streams",
            "-of", "json", str(temporary),
        ], timeout=30))
        if len([s for s in probe["streams"] if s["codec_type"] == "video"]) != 1:
            raise ValueError("Expected one video stream")
        temporary.rename(final)
        record.update({"path": str(final.relative_to(ROOT)), "sha256": media_hash,
                       "bytes": total, "probe": probe, "success": True})
    except Exception as error:
        record.update({"success": False, "error": str(error), "errorType": type(error).__name__})
    record["finishedAt"] = datetime.now(timezone.utc).isoformat()
    return record


def main():
    if OUTPUT.exists():
        raise ValueError("Prior acquisition receipt is immutable")
    source_bytes = HEADS.read_bytes()
    rows = [r for r in json.loads(source_bytes)["files"] if r["id"] in SELECTED]
    if len(rows) != 3 or {r["id"] for r in rows} != SELECTED:
        raise ValueError("Exact audited source selection is required")
    MEDIA.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        records = list(executor.map(acquire, rows))
    receipt = {"purpose": "camera source acquisition and media probe; no detector calls",
               "headsSha256": hashlib.sha256(source_bytes).hexdigest(),
               "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "sourceAssessment": "eval/INDEPENDENT_CAMERA_SOURCE_FEASIBILITY.md",
               "selected": 3, "completed": sum(r["success"] for r in records),
               "visualInspectionComplete": False, "records": records}
    with OUTPUT.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    for r in records:
        print(json.dumps({k: r.get(k) for k in ["id", "success", "path", "sha256", "bytes", "error"]}))
    if receipt["completed"] != 3:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
