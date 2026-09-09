#!/usr/bin/env python3
"""Build three frozen development diagnostics from one receipt-backed generation."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "eval/generated-origin-manifest.jsonl"
if MANIFEST.exists():
    raise RuntimeError("Preserve the existing generated-control manifest; do not overwrite it.")
receipt = json.loads((ROOT / "eval/fixtures/video-generation-receipt.json").read_text())
plan_bytes = (ROOT / "eval/fixtures/video-generation-plan.json").read_bytes()
assert hashlib.sha256(plan_bytes).hexdigest() == receipt["planSha256"]
assert receipt["inputMedia"] == [] and receipt["generationSubmissions"] == 1
generated = ROOT / receipt["download"]["path"]
assert hashlib.sha256(generated.read_bytes()).hexdigest() == receipt["download"]["sha256"]
cgi = ROOT / "eval/media/controls/source.mp4"
cgi_hash = hashlib.sha256(cgi.read_bytes()).hexdigest()
source_cgi = "https://media.w3.org/2010/05/sintel/trailer.mp4"
group_ai = "generated-operation:" + receipt["operationName"]
group_cgi = "sintel-2010"
normal = "fps=24,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1"
rows = []
commands = []

def emit(name, label, inputs, graph, parents, intervals, origin):
    opaque = hashlib.sha256((receipt["planSha256"] + name).encode()).hexdigest()[:24]
    output = ROOT / "eval/media/controls" / (opaque + ".mp4")
    args = ["ffmpeg", "-nostdin", "-n", "-v", "error", *inputs, "-filter_complex", graph,
            "-map", "[out]", "-t", "8", "-r", "24", "-fps_mode", "cfr", "-an", "-map_metadata", "-1", "-c:v", "libx264",
            "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", str(output)]
    subprocess.run(args, check=True, timeout=60)
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(output)], timeout=30))
    streams = probe["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    assert len(streams) == 1 and video["width"] == 1280 and video["height"] == 720
    assert video["avg_frame_rate"] == "24/1" and float(probe["format"]["duration"]) == 8
    assert output.stat().st_size < 20_000_000
    row = {"id": opaque, "groupId": "known-origin-development-family", "split": "development", "label": label,
           "path": str(output.relative_to(ROOT)), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
           "dataset": "receipt-backed-development-controls", "generator": "veo-3.1-generate-preview" if label != "cgi" else "none",
           "platform": "upload", "mimeType": "video/mp4", "transformation": name, "parentGroups": parents,
           "sourceUrl": source_cgi if label == "cgi" else "https://ai.google.dev/gemini-api/docs/veo",
           "license": "Sintel CC BY 3.0 attribution applies to CGI excerpts; generated output retained for local evaluation",
           "groundTruth": {"basis": origin, "generationReceipt": "eval/fixtures/video-generation-receipt.json" if label != "cgi" else None,
                           "aiIntervalSeconds": intervals, "cgiSourceSha256": cgi_hash if label != "ai" else None,
                           "cgiSourceUrl": source_cgi if label != "ai" else None,
                           "edit": "Eight-second timeline; mixed variant replaces control seconds3-5 with generated seconds3-5.",
                           "limitation": "One generated source and one 2010 conventional CGI source. No camera-origin population estimate."},
           "media": {"bytes": output.stat().st_size, "durationSeconds": 8, "width": 1280, "height": 720, "frameRate": "24/1", "hasAudio": False}}
    rows.append(row)
    commands.append({"id": opaque, "arguments": args, "probe": probe})

emit("generated-whole-silent", "ai", ["-i", str(generated)], f"[0:v]{normal},setpts=PTS-STARTPTS[out]",
     [group_ai], [0, 8], "Direct text-only Google generation operation, original SHA-256, deterministic silent derivative.")
emit("cgi-eight-second-silent", "cgi", ["-ss", "12", "-i", str(cgi)], f"[0:v]{normal},trim=duration=8,setpts=PTS-STARTPTS[out]",
     [group_cgi], [], "Blender Foundation Sintel2010 conventional CGI, source seconds12-20, CC BY3.0.")
mixed = (f"[0:v]{normal},split=2[a][b];[a]trim=duration=3,setpts=PTS-STARTPTS[pre];"
         "[b]trim=start=5:duration=3,setpts=PTS-STARTPTS[post];"
         f"[1:v]{normal},trim=start=3:duration=2,setpts=PTS-STARTPTS[ai];"
         "[pre][ai][post]concat=n=3:v=1:a=0[out]")
emit("cgi-with-two-second-generated-insert", "mixed", ["-ss", "12", "-i", str(cgi), "-i", str(generated)], mixed,
     [group_cgi, group_ai], [3, 5], "Deterministic edit of documented2010 CGI and the text-only generation output; exact parent and operation hashes retained.")
MANIFEST.write_text("".join(json.dumps(row) + "\n" for row in rows))
execution = {"planSha256": receipt["planSha256"], "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "manifestSha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(), "cgiSourceSha256": cgi_hash,
             "generatedSourceSha256": receipt["download"]["sha256"], "commands": commands}
(ROOT / "eval/fixtures/generated-control-build-receipt.json").write_text(json.dumps(execution, indent=2) + "\n")
print(json.dumps({"manifest": str(MANIFEST.relative_to(ROOT)), "controls": len(rows), "ids": [r["id"] for r in rows]}))
