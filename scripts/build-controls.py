#!/usr/bin/env python3
"""Reproducible development-only CGI and short AI-insert controls."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "eval/control-manifest.jsonl"
if MANIFEST.exists():
    raise RuntimeError("The existing controls are frozen evaluation evidence. Use a new study/output path instead of overwriting them.")
MEDIA = ROOT / "eval/media/controls"
MEDIA.mkdir(parents=True, exist_ok=True)
SOURCE = "https://media.w3.org/2010/05/sintel/trailer.mp4"
source = MEDIA / "source.mp4"
if not source.exists():
    with urllib.request.urlopen(SOURCE, timeout=30) as response:
        data = response.read(30_000_001)
    if len(data) > 30_000_000:
        raise RuntimeError("Control source exceeds the 30 MB limit")
    source.write_bytes(data)

rows = []
def emit(name, label, group, args, truth, source_url, parents=None):
    opaque = hashlib.sha256(name.encode()).hexdigest()[:24]
    output = MEDIA / f"{opaque}.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-n", "-v", "error", *args,
                    "-r", "24", "-fps_mode", "cfr", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", str(output)], check=True, timeout=60)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)]))
    stream = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    rows.append({"id": opaque, "groupId": group, "split": "development", "label": label,
        "path": str(output.relative_to(ROOT)), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "sourceUrl": source_url, "license": "CC BY 3.0" if label == "cgi" else "MIT (GenBuster-Bench source clips)",
        "groundTruth": truth, "dataset": "constructed-controls", "generator": "none" if label == "cgi" else "mixed",
        "platform": "upload", "transformation": name, "mimeType": "video/mp4", "parentGroups": parents or [],
        "media": {"durationSeconds": float(probe["format"]["duration"]), "width": stream["width"], "height": stream["height"], "frameRate": stream["avg_frame_rate"], "hasAudio": False}})

for second in [12, 30, 42]:
    emit(f"conventional-cgi-{second}", "cgi", "sintel-2010", ["-ss", str(second), "-i", str(source), "-t", "6"],
         "Excerpt from Blender Foundation's 2010 conventionally animated Sintel trailer; https://durian.blender.org/sharing/ documents CC BY license and https://studio.blender.org/films/ documents 2010 production. No generative AI rendering.", SOURCE)

smoke = [json.loads(line) for line in (ROOT / "eval/smoke-manifest.jsonl").read_text().splitlines()]
real = next(row for row in smoke if row["label"] == "real")
ai = next(row for row in smoke if row["generator"] == "wan2.6")
for insert in [0.5, 1, 2]:
    graph = (
        "[0:v]fps=24,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,split=2[a][c];"
        "[a]trim=duration=5,setpts=PTS-STARTPTS[pre];"
        "[c]trim=start=5:duration=5,setpts=PTS-STARTPTS[post];"
        f"[1:v]fps=24,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,trim=duration={insert},setpts=PTS-STARTPTS[insert];"
        "[pre][insert][post]concat=n=3:v=1:a=0[out]"
    )
    emit(f"ai-insert-{insert}s", "mixed", "constructed-mixed-development", [
        "-stream_loop", "-1", "-i", str(ROOT / real["path"]), "-i", str(ROOT / ai["path"]),
        "-filter_complex", graph, "-map", "[out]", "-t", str(10 + insert)],
        {"method": "Deterministic FFmpeg concatenation of author-labeled real and generated development clips.",
         "aiIntervalSeconds": [5, 5 + insert], "parents": [real["id"], ai["id"]],
         "limitation": "Source labels are dataset-author assertions, not independent camera authentication."},
        ai["sourceUrl"], [real["groupId"], ai["groupId"]])

MANIFEST.write_text("".join(json.dumps(row) + "\n" for row in rows))
print(json.dumps({"controls": len(rows), "split": "development", "manifest": "eval/control-manifest.jsonl"}))
