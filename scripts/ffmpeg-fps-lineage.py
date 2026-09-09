"""Fail-closed native-frame lineage from one FFmpeg 7.0 fps debug trace.

Indices are zero-based decoded input order, not a PTS lookup or a pixel match.
Intended for a complete, zero-origin, one-input 24->12 or 24->24 study render.
Use ``-nostats -loglevel debug`` and let the graph drain (no output frame cap).
Only one active unnamed ``fps`` filter, strictly increasing native input PTS,
consecutive zero-based output PTS, and zero duplicated output frames are allowed.
Repeated *pixel content* is supported; missing/duplicated log events are errors.

FFmpeg's fps filter logs reads, zero-use drops and output clones, but silently
retires a frame used exactly once. With zero output duplication certified by
the final counters, retiring that input at its write is equivalent for FIFO
lineage. The two-slot bound, PTS and final counts cross-check that reconstruction.
Reference: https://github.com/FFmpeg/FFmpeg/blob/n7.0/libavfilter/vf_fps.c
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
import argparse
import json
import re


class FpsLineageError(ValueError):
    """The trace does not establish complete, unambiguous frame lineage."""


_PREFIX = re.compile(r"^\[(Parsed_fps_\d+ @ 0x[0-9a-fA-F]+)\] (.+)$")
_SUMMARY = re.compile(r"(\d+) frames in, (\d+) frames out; (\d+) frames dropped, (\d+) frames duplicated\.")
_READ = re.compile(r"Read frame with in pts (-?\d+), out pts (-?\d+)")
_WRITE = re.compile(r"Writing frame with pts (-?\d+) to pts (-?\d+)")
_DROP = re.compile(r"Dropping frame with pts (-?\d+)")
_FPS = re.compile(r"fps=(\d+)/(\d+)")
_FIRST = re.compile(r"Set first pts to (-?\d+)")
_EOF = re.compile(r"EOF is at pts (-?\d+)")


def parse_fps_lineage(stderr: str, expectedInputFrames: int,
                      expectedOutputFrames: int) -> list[int]:
    """Return input indices for output order, or raise FpsLineageError.

    This validates filter lineage, not downstream encoder/muxer behavior. The
    caller must also verify subprocess success and encoded frame count/PTS.
    Rejects resampling with duplicated output frames instead of guessing when a
    silently retired frame was consumed. Known duplicate input images are fine.
    """
    def require(condition, message):
        if not condition:
            raise FpsLineageError(message)

    require(isinstance(stderr, str), "stderr must be text")
    require(type(expectedInputFrames) is int and type(expectedOutputFrames) is int
            and 0 < expectedOutputFrames <= expectedInputFrames,
            "Expected positive counts without output duplication")
    versions = re.findall(r"^ffmpeg version (\S+)", stderr, re.MULTILINE)
    require(versions == ["7.0"], "Require one pinned FFmpeg 7.0 process log")
    groups: dict[str, list[str]] = {}
    for line in stderr.splitlines():
        require(re.search(r"\[fps@", line) is None,
                "Named fps filters are outside this single-filter contract")
        if "Parsed_fps_" not in line:
            continue
        match = _PREFIX.fullmatch(line)
        require(match is not None, "Malformed or interleaved fps trace line")
        identity, message = match.groups()
        groups.setdefault(identity, []).append(message)
    # FFmpeg builds and destroys an unused graph while configuring the output.
    # Only a single exact all-zero summary can identify such a harmless graph.
    active = [messages for messages in groups.values() if messages != [
        "0 frames in, 0 frames out; 0 frames dropped, 0 frames duplicated."]]
    require(len(active) == 1, "Require exactly one active fps filter instance")
    messages = active[0]
    require(_FPS.fullmatch(messages[0]) is not None,
            "Active trace must begin with fps configuration")
    rate = tuple(map(int, _FPS.fullmatch(messages[0]).groups()))
    require(rate in [(12, 1), (24, 1)], "Study permits only fps=12 or fps=24")
    queue: deque[tuple[int, int]] = deque()
    selected: list[int] = []
    read_count = drop_count = 0
    last_native = last_rescaled = None
    first_seen = eof_seen = summary_seen = False
    for message in messages[1:]:
        require(not summary_seen, "Unexpected event after final summary")
        if match := _READ.fullmatch(message):
            native, rescaled = map(int, match.groups())
            require(not eof_seen, "Read after EOF")
            require(read_count < expectedInputFrames, "Too many input reads")
            require(native >= 0 and rescaled >= 0, "Negative/missing input PTS")
            require(last_native is None or native > last_native,
                    "Duplicate or non-monotonic native input PTS")
            require(last_rescaled is None or rescaled >= last_rescaled,
                    "Non-monotonic rescaled input PTS")
            require(read_count > 0 or (native == 0 and rescaled == 0),
                    "Study master must start at zero PTS")
            queue.append((read_count, rescaled))
            require(len(queue) <= 2, "FIFO overflow: missing or reordered event")
            read_count += 1
            last_native, last_rescaled = native, rescaled
        elif match := _FIRST.fullmatch(message):
            require(not first_seen and read_count == 2 and not selected
                    and int(match.group(1)) == 0, "Invalid/duplicate first PTS")
            first_seen = True
        elif match := _WRITE.fullmatch(message):
            source_pts, output_pts = map(int, match.groups())
            require(first_seen and queue, "Write without an available input")
            require(len(selected) < expectedOutputFrames,
                    "Too many output writes")
            require(output_pts == len(selected), "Missing/duplicate output PTS")
            require(source_pts == queue[0][1], "Write violates FIFO source PTS")
            require(len(queue) == 2 or eof_seen,
                    "Write lacks next input or EOF lookahead")
            selected.append(queue.popleft()[0])
        elif match := _DROP.fullmatch(message):
            require(first_seen and queue, "Drop without an available input")
            require(int(match.group(1)) == queue[0][1],
                    "Drop violates FIFO source PTS")
            queue.popleft()
            drop_count += 1
        elif match := _EOF.fullmatch(message):
            require(not eof_seen and first_seen, "Invalid/duplicate EOF")
            require(read_count == expectedInputFrames, "EOF before all inputs")
            require(int(match.group(1)) == expectedOutputFrames,
                    "EOF timestamp differs from expected full duration")
            eof_seen = True
        elif match := _SUMMARY.fullmatch(message):
            counts = tuple(map(int, match.groups()))
            require(eof_seen and first_seen, "Missing EOF/initial PTS trace")
            require(counts == (expectedInputFrames, expectedOutputFrames,
                               expectedInputFrames-expectedOutputFrames, 0),
                    "Final counts differ or fps duplicated output frames")
            require(read_count == counts[0] and len(selected) == counts[1]
                    and drop_count == counts[2] and not queue,
                    "Missing/duplicated trace events or unconsumed inputs")
            summary_seen = True
        else:
            raise FpsLineageError("Unexpected fps event: " + message)
    require(summary_seen, "Missing final fps summary")
    require(len(set(selected)) == len(selected), "Repeated output input index")
    return selected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stderr", type=Path)
    parser.add_argument("expectedInputFrames", type=int)
    parser.add_argument("expectedOutputFrames", type=int)
    args = parser.parse_args()
    print(json.dumps(parse_fps_lineage(args.stderr.read_text(),
                                     args.expectedInputFrames,
                                     args.expectedOutputFrames)))
