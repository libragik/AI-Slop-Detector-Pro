#!/usr/bin/env python3
"""Create deterministic social-media-like derivatives, preserving source splits."""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("corpus", ROOT / "scripts/eval-download-corpus.py")
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)

parser = argparse.ArgumentParser()
parser.add_argument("--manifest", default="eval/manifest.jsonl")
parser.add_argument("--output", default="eval/transformed-manifest.jsonl")
parser.add_argument("--limit", type=int)
args = parser.parse_args()
originals = [json.loads(line) for line in (ROOT / args.manifest).read_text().splitlines() if line]
originals = [row for row in originals if row["transformation"] == "original"][:args.limit]
recipes = {
    "social_720p_crf28": ["-vf", "scale='min(720,iw)':-2,fps=24", "-crf", "28"],
    "repost_360p_crf36_12fps_crop": ["-vf", "crop=trunc(iw*0.85/2)*2:trunc(ih*0.85/2)*2,scale='min(360,iw)':-2,fps=12,drawbox=x=0:y=0:w=iw:h=ih*0.08:color=black@0.8:t=fill", "-crf", "36"],
}


def transform(item):
    original, name, flags = item
    opaque_id = hashlib.sha256((original["id"] + ":" + name + ":v1").encode()).hexdigest()[:24]
    path = ROOT / f"eval/media/{opaque_id}.mp4"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(ROOT / original["path"]),
               "-map", "0:v:0", "-an", *flags, "-c:v", "libx264", "-preset", "veryfast", "-threads", "2",
               "-pix_fmt", "yuv420p", "-map_metadata", "-1", "-movflags", "+faststart", str(path)]
    if not path.exists():
        subprocess.run(command, check=True, timeout=90)
    return {**original, "id": opaque_id, "path": str(path.relative_to(ROOT)), "parentId": original["id"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "media": corpus.probe(path),
            "transformation": name, "platform": "simulated_social",
            "transformRecipe": {"version": 1, "arguments": command[command.index("-map"): -1],
                                "note": "Controlled simulation; not an actual Instagram/TikTok/X/YouTube reupload. Audio removed in this visual robustness test."}}


items = [(row, name, flags) for row in originals for name, flags in recipes.items()]
rows = list(originals)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for count, row in enumerate(pool.map(transform, items), 1):
        rows.append(row)
        if count % 25 == 0 or count == len(items):
            print(json.dumps({"transformed": count, "total": len(items)}), flush=True)
(ROOT / args.output).write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in sorted(rows, key=lambda x: x["id"])))
print(json.dumps({"manifest": args.output, "clips": len(rows), "sourceGroups": len(set(r["groupId"] for r in rows))}))
