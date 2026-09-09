#!/usr/bin/env bash
set -euo pipefail

media_repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
media_python="${PYTHON_MEDIA:-python3}"
if ! command -v "$media_python" >/dev/null 2>&1; then
  printf '%s\n' 'Python 3.10+ was not found. Install python3 or set PYTHON_MEDIA to its executable path.' >&2
  exit 1
fi
"$media_python" -c 'import sys; sys.exit("Python 3.10+ is required.") if sys.version_info < (3, 10) else None'

"$media_python" -m venv "$media_repo_dir/.venv-media"
"$media_repo_dir/.venv-media/bin/python" -m pip install --quiet --disable-pip-version-check \
  --requirement "$media_repo_dir/requirements-media.txt"

# Change only the local downloader setting. Never echo the environment file or
# provider credentials. Keep the existing file mode and all unrelated lines.
"$media_repo_dir/.venv-media/bin/python" - "$media_repo_dir" <<'PY'
import json
import os
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
env_path = root / ".env.local"
original = env_path.read_bytes() if env_path.exists() else b""
replacement = ("YT_DLP_PATH=" + json.dumps(str(root / ".venv-media/bin/yt-dlp"))).encode()
updated = []
matched = False
for line in original.splitlines(keepends=True):
    if re.match(rb"^\s*(?:export\s+)?YT_DLP_PATH\s*=", line):
        ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
        updated.append(replacement + ending)
        matched = True
    else:
        updated.append(line)
if not matched:
    if original and not original.endswith((b"\n", b"\r")):
        updated.append(b"\n")
    updated.append(replacement + b"\n")
# New credential files are owner-only; an existing file keeps its permissions.
with os.fdopen(os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as handle:
    handle.write(b"".join(updated))
PY

printf '%s' 'Project media downloader ready: '
"$media_repo_dir/.venv-media/bin/yt-dlp" --version
