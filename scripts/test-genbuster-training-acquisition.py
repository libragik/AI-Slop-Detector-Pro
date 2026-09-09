#!/usr/bin/env python3
"""Offline contracts: synthetic ZIP bytes and mocked transport only."""
import concurrent.futures
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

SPEC = importlib.util.spec_from_file_location("acquisition", Path(__file__).with_name("acquire-genbuster-training-subset.py"))
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def fixture(method=zipfile.ZIP_DEFLATED, body=b"synthetic-contract-bytes" * 20):
    stream = io.BytesIO()
    name = "train/fake/cogvideox/" + "a" * 64 + ".mp4"
    with zipfile.ZipFile(stream, "w", compression=method) as archive:
        archive.writestr(name, body)
    raw = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        item = archive.infolist()[0]
    entry = {"name": name, "flags": item.flag_bits, "method": item.compress_type, "crc32": f"{item.CRC:08x}",
             "compressedBytes": item.compress_size, "uncompressedBytes": item.file_size, "localHeaderOffset": item.header_offset}
    row = {"id": "b" * 64, "parentId": "b" * 64, "archiveMember": name, "zip": entry,
           "entryBoundary": len(raw), "path": A.MEDIA_DIR + "/" + "b" * 64 + ".mp4"}
    return raw, row, body


def transport(raw, calls):
    def fetch(start, count, *unused):
        calls.append((start, count))
        return raw[start:start + count]
    return fetch


class Response(io.BytesIO):
    def __init__(self, body, start, count, status=206, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Range": f"bytes {start}-{start + count - 1}/{A.ARCHIVE_BYTES}",
                        "Content-Length": str(count), "ETag": A.ETAG}
        self.headers.update(headers or {})


class Opener:
    def __init__(self, response):
        self.response, self.calls = response, 0

    def open(self, *args, **kwargs):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Contracts(unittest.TestCase):
    def test_both_zip_methods_and_exact_three_ranges(self):
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(method=method):
                raw, row, expected = fixture(method)
                calls = []
                result, receipt = A.download_member(row, transport(raw, calls))
                self.assertEqual(result, expected)
                self.assertEqual(len(calls), 3)
                self.assertEqual(calls[0], (0, 30))
                self.assertEqual(calls[1], (30, len(row["archiveMember"])))
                self.assertEqual(calls[2][1], row["zip"]["compressedBytes"])
                self.assertEqual(receipt["compressedSha256"], A.sha(raw[calls[2][0]:sum(calls[2])]))

    def test_header_mutations_reject_before_payload(self):
        raw, row, _ = fixture()
        for offset, value in [(0, b"BAD!"), (4, struct.pack("<H", 0)), (6, struct.pack("<H", 1)),
                              (8, struct.pack("<H", 0)), (14, struct.pack("<I", 1)),
                              (26, struct.pack("<H", 1)), (28, struct.pack("<H", A.MAX_EXTRA + 1))]:
            with self.subTest(offset=offset):
                damaged = bytearray(raw); damaged[offset:offset + len(value)] = value
                calls = []
                with self.assertRaises(A.IntegrityError):
                    A.download_member(row, transport(bytes(damaged), calls))
                self.assertEqual(len(calls), 1)

    def test_local_sizes_and_name_are_checked_before_payload(self):
        raw, row, _ = fixture()
        for offset, value in [(18, struct.pack("<I", 1)), (22, struct.pack("<I", 1)), (30, b"X")]:
            with self.subTest(offset=offset):
                damaged = bytearray(raw); damaged[offset:offset + len(value)] = value
                calls = []
                with self.assertRaises(A.IntegrityError):
                    A.download_member(row, transport(bytes(damaged), calls))
                self.assertEqual(len(calls), 2)

    def test_traversal_and_unsupported_central_metadata(self):
        _, row, _ = fixture()
        for key, value in [("name", "../x.mp4"), ("name", "train/real/../x.mp4"),
                           ("name", "/train/real/" + "a" * 64 + ".mp4"), ("name", "train\\real\\x.mp4"),
                           ("method", 99), ("flags", 8), ("flags", 1), ("compressedBytes", A.MAX_MEMBER + 1),
                           ("uncompressedBytes", A.MAX_MEMBER + 1), ("compressedBytes", True),
                           ("localHeaderOffset", A.CENTRAL_OFFSET), ("crc32", "XYZ")]:
            with self.subTest(key=key, value=value):
                entry = dict(row["zip"], **{key: value})
                with self.assertRaises(A.IntegrityError):
                    A.validate_entry(entry)

    def test_entry_cannot_cross_boundary(self):
        raw, row, _ = fixture()
        row["entryBoundary"] = 40
        calls = []
        with self.assertRaises(A.IntegrityError):
            A.download_member(row, transport(raw, calls))
        self.assertEqual(len(calls), 1)

    def test_zip64_local_sizes(self):
        _, row, _ = fixture()
        e = row["zip"]
        h = {"size": 0xFFFFFFFF, "compressed": 0xFFFFFFFF, "nameBytes": len(e["name"]), "extraBytes": 20}
        extra = struct.pack("<HHQQ", 1, 16, e["uncompressedBytes"], e["compressedBytes"])
        A.verify_local_fields(e["name"].encode() + extra, h, e)
        for bad in [extra[:-1], extra + b"x", struct.pack("<HHQQ", 1, 16, 1, 1)]:
            with self.subTest(bad=bad), self.assertRaises(A.IntegrityError):
                A.verify_local_fields(e["name"].encode() + bad, h, e)

    def test_malformed_duplicate_extra_rejected(self):
        _, row, _ = fixture()
        e = row["zip"]
        for extra in [b"x", struct.pack("<HH", 7, 20), struct.pack("<HHHH", 7, 0, 7, 0)]:
            with self.subTest(extra=extra):
                h = {"size": e["uncompressedBytes"], "compressed": e["compressedBytes"], "nameBytes": len(e["name"]), "extraBytes": len(extra)}
                with self.assertRaises(A.IntegrityError):
                    A.verify_local_fields(e["name"].encode() + extra, h, e)

    def test_decompression_crc_truncation_trailing_and_bomb_bounds(self):
        raw, row, expected = fixture()
        e = row["zip"]
        p = raw[30 + len(e["name"]):30 + len(e["name"]) + e["compressedBytes"]]
        cases = [(p[:-1], dict(e, compressedBytes=len(p) - 1)),
                 (p + b"trailing", dict(e, compressedBytes=len(p) + 8)),
                 (p, dict(e, uncompressedBytes=len(expected) - 1)),
                 (p, dict(e, crc32="00000000"))]
        c = zlib.compressobj(wbits=-15); bomb = c.compress(b"A" * 1_000_000) + c.flush()
        cases.append((bomb, dict(e, compressedBytes=len(bomb), uncompressedBytes=100)))
        for payload, metadata in cases:
            with self.subTest(metadata=metadata), self.assertRaises(A.IntegrityError):
                A.decode_member(payload, metadata)

    def test_http_contract_and_no_automatic_retry(self):
        self.assertEqual(A.fetch_range(10, 3, Opener(Response(b"abc", 10, 3))), b"abc")
        for response in [Response(b"abc", 10, 3, status=200),
                         Response(b"abc", 10, 3, headers={"Content-Range": "bytes 10-12/999"}),
                         Response(b"abc", 10, 3, headers={"Content-Length": "4"}),
                         Response(b"abc", 10, 3, headers={"ETag": '"wrong"'}),
                         Response(b"abc", 10, 3, headers={"Content-Encoding": "gzip"}), Response(b"abcd", 10, 3)]:
            opener = Opener(response)
            with self.subTest(headers=response.headers), self.assertRaises(A.IntegrityError):
                A.fetch_range(10, 3, opener)
            self.assertEqual(opener.calls, 1)
        for response in [Response(b"ab", 10, 3), TimeoutError("secret-signed-url")]:
            opener = Opener(response)
            with self.assertRaises(A.TechnicalError) as error:
                A.fetch_range(10, 3, opener)
            self.assertNotIn("secret", str(error.exception))
            self.assertEqual(opener.calls, 1)

    def test_redirect_scope(self):
        A.valid_redirect("https://cas-bridge.xethub.hf.co/blob?temporary=signed")
        for url in ["http://huggingface.co/file", "file:///tmp/private", "https://127.0.0.1/file", "https://huggingface.co.evil.test/file", "https://user:secret@huggingface.co/file", "https://huggingface.co:444/file"]:
            with self.subTest(url=url), self.assertRaises(A.IntegrityError):
                A.valid_redirect(url)

    def test_budget_atomic_parallel_reservation_and_persistent_resume(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.jsonl"
            budget = A.Budget(path, 20)
            calls = []
            def work(i):
                try:
                    budget.fetch(str(i), 1, 0, 4, "test", lambda *args: calls.append(args) or b"1234")
                    return True
                except A.IntegrityError:
                    return False
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                result = list(pool.map(work, range(8)))
            self.assertEqual(sum(result), 4)
            self.assertEqual(len(calls), 4)
            resumed = A.Budget(path, 20)
            self.assertEqual(resumed.reserved, 20)
            with self.assertRaises(A.IntegrityError):
                resumed.fetch("x", 1, 0, 1, "test", lambda *args: self.fail("No network after budget exhaustion"))

    def test_failed_transport_reservation_is_not_refunded(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "journal.jsonl"
            with self.assertRaises(A.TechnicalError):
                A.Budget(path, 100).fetch("x", 1, 0, 30, "header", lambda *args: (_ for _ in ()).throw(A.TechnicalError("interrupted")))
            self.assertEqual(A.Budget(path, 100).reserved, 31)
            path.write_bytes(path.read_bytes() + b"{partial")
            with self.assertRaises(A.IntegrityError):
                A.Budget(path, 100)

    def test_resume_hashes_media_and_uses_no_transport(self):
        raw, row, expected = fixture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / A.MEDIA_DIR).mkdir(parents=True)
            (root / A.RUN_DIR / "members").mkdir(parents=True)
            budget = A.Budget(root / A.RUN_DIR / "journal.jsonl")
            calls = []
            receipt = A.acquire_one(root, row, budget, "frozen", set(), transport=transport(raw, calls), probe=lambda p: {"syntheticFixture": True})
            self.assertEqual(len(calls), 3)
            self.assertEqual(receipt["sha256"], A.sha(expected))
            again = A.acquire_one(root, row, budget, "frozen", set(), transport=lambda *args: self.fail("Resume must not download"))
            self.assertEqual(again, receipt)
            (root / row["path"]).write_bytes(expected[:-1] + b"X")
            with self.assertRaises(A.IntegrityError):
                A.acquire_one(root, row, budget, "frozen", set(), transport=lambda *args: self.fail("Corrupt cache must not be replaced"))

    def test_one_explicit_technical_retry_and_no_replacement(self):
        raw, row, _ = fixture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / A.MEDIA_DIR).mkdir(parents=True)
            (root / A.RUN_DIR / "members").mkdir(parents=True)
            budget = A.Budget(root / A.RUN_DIR / "journal.jsonl")
            fail = lambda *args: (_ for _ in ()).throw(A.TechnicalError("network stopped"))
            with self.assertRaises(A.TechnicalError):
                A.acquire_one(root, row, budget, "pin", set(), transport=fail)
            with self.assertRaises(A.IntegrityError):
                A.acquire_one(root, row, budget, "pin", set(), transport=lambda *args: self.fail("No implicit retry"))
            with self.assertRaises(A.TechnicalError):
                A.acquire_one(root, row, budget, "pin", set(), retry_failed=True, transport=fail)
            with self.assertRaises(A.IntegrityError):
                A.acquire_one(root, row, budget, "pin", set(), retry_failed=True, transport=lambda *args: self.fail("Third attempt forbidden"))
            state = json.loads((root / A.RUN_DIR / "members" / (row["id"] + ".json")).read_text())
            self.assertEqual(len(state["attempts"]), 2)
            self.assertFalse((root / row["path"]).exists())

    def test_content_exclusion_integrity_failure_never_retried(self):
        raw, row, body = fixture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / A.MEDIA_DIR).mkdir(parents=True)
            (root / A.RUN_DIR / "members").mkdir(parents=True)
            budget = A.Budget(root / A.RUN_DIR / "journal.jsonl")
            with self.assertRaises(A.IntegrityError):
                A.acquire_one(root, row, budget, "pin", {A.sha(body)}, transport=transport(raw, []), probe=lambda p: self.fail("Excluded bytes not probed"))
            with self.assertRaises(A.IntegrityError):
                A.acquire_one(root, row, budget, "pin", set(), retry_failed=True, transport=lambda *args: self.fail("Integrity failure not retriable"))

    def test_no_overwrite_or_symlink_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); target = root / "existing"; target.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                A.write_new(target, b"replace")
            self.assertEqual(target.read_bytes(), b"keep")
            (root / "link").symlink_to(target)
            for fn in [lambda: A.safe_path(root, "link"), lambda: A.read_file(root / "link"), lambda: A.safe_path(root, "../escape")]:
                with self.assertRaises(A.IntegrityError):
                    fn()

    def test_real_metadata_selection_is_deterministic_disjoint_and_quota_bound(self):
        with patch.object(A.urllib.request, "urlopen", side_effect=AssertionError("Offline plan may not network")):
            plan = A.make_plan()
            self.assertEqual(plan, A.make_plan())
        rows = plan["entries"]
        self.assertEqual(len(rows), 2304)
        self.assertEqual(len({r["id"] for r in rows}), 2304)
        self.assertEqual(plan["excludedArchiveMembers"], [])
        for split, count_real, count_gen in [("train", 1024, 256), ("internal_development", 128, 32)]:
            self.assertEqual(sum(r["split"] == split and r["label"] == "real" for r in rows), count_real)
            for gen in A.GENERATORS:
                self.assertEqual(sum(r["split"] == split and r["generator"] == gen for r in rows), count_gen)
        for gen in (None, *A.GENERATORS):
            t = [r["selectionRankSha256"] for r in rows if r["split"] == "train" and r["generator"] == gen]
            v = [r["selectionRankSha256"] for r in rows if r["split"] == "internal_development" and r["generator"] == gen]
            self.assertLess(max(t), min(v))
        self.assertEqual(plan["bytes"]["compressedMedia"], 1_339_935_309)
        self.assertEqual(plan["bytes"]["uncompressedMedia"], 1_345_109_554)
        registered = [json.loads(x) for x in (A.ROOT / "eval/manifest.jsonl").read_text().splitlines()]
        self.assertTrue({r["sha256"] for r in registered}.issubset(plan["excludedKnownMediaSha256"]))

    def test_unfrozen_or_modified_plan_rejected_before_network(self):
        plan = A.make_plan()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plan.json"
            p.write_bytes(A.json_bytes(plan))
            with self.assertRaises(A.IntegrityError):
                A.load_frozen(p, A.sha(p.read_bytes()))
            plan["frozen"] = True; plan["frozenAt"] = "2026-09-05T00:00:00+00:00"
            p.write_bytes(A.json_bytes(plan))
            self.assertEqual(A.load_frozen(p, A.sha(p.read_bytes())), plan)
            with self.assertRaises(A.IntegrityError):
                A.load_frozen(p, "0" * 64)
            plan["entries"][0]["label"] = "ai"
            p.write_bytes(A.json_bytes(plan))
            with self.assertRaises(A.IntegrityError):
                A.load_frozen(p, A.sha(p.read_bytes()))

    def test_completion_contract_and_duplicate_content_abort(self):
        _, first, _ = fixture()
        second = dict(first, id="c" * 64, parentId="c" * 64, path=A.MEDIA_DIR + "/" + "c" * 64 + ".mp4")
        for row, split in [(first, "train"), (second, "internal_development")]:
            row.update(split=split, label="ai", generator="cogvideox", groupId=row["id"])
        plan = {"entries": [first, second], "excludedKnownMediaSha256": ["e" * 64], "dataset": "synthetic-contract",
                "labelBasis": "synthetic-test", "limitations": ["not media"], "license": "test", "counts": {"total": 2}}
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                def completed(root, row, *args):
                    return {"sha256": "d" * 64 if duplicate else row["id"], "bytes": 20, "media": {"synthetic": True}}
                with patch.object(A, "acquire_one", completed), patch.object(A, "verify_live_bindings"), patch("builtins.print"):
                    if duplicate:
                        with self.assertRaises(A.IntegrityError):
                            A.run_acquisition(plan, "pin", 2, root=root)
                        self.assertFalse((root / A.RUN_DIR / "completion.json").exists())
                        self.assertFalse((root / A.RUN_DIR / "manifest.jsonl").exists())
                    else:
                        A.run_acquisition(plan, "pin", 2, root=root)
                        completion = json.loads((root / A.RUN_DIR / "completion.json").read_text())
                        manifest = (root / A.RUN_DIR / "manifest.jsonl").read_bytes()
                        self.assertEqual(completion["manifestSha256"], A.sha(manifest))
                        self.assertEqual(completion["uniqueContentHashes"], 2)
                        self.assertEqual(completion["actualUncompressedBytes"], 40)
                        self.assertTrue(completion["complete"])
                        rows = [json.loads(line) for line in manifest.splitlines()]
                        self.assertEqual([r["split"] for r in rows], ["train", "internal_development"])
                        self.assertTrue(all(r["bytes"] == 20 and r["acquisitionFixtureSha256"] == "pin" for r in rows))

    def test_basename_or_crc_size_exclusion_precedes_ranking(self):
        census = json.loads((A.ROOT / "eval/sources/training-source-audit/zip-entry-census.json").read_text())
        original, _ = A.select_entries(census, {"entries": []}, [])
        first, second = original[:2]
        benchmark = {"entries": [{"path": "bench/" + Path(first["archiveMember"]).name, "crc": 0, "size": 1},
                                 {"path": "bench/nonmatching.mp4", "crc": int(second["zip"]["crc32"], 16), "size": second["zip"]["uncompressedBytes"]}]}
        rows, excluded = A.select_entries(census, benchmark, [])
        self.assertEqual(len(rows), 2304)
        self.assertEqual(set(excluded), {first["archiveMember"], second["archiveMember"]})
        self.assertTrue(set(excluded).isdisjoint(r["archiveMember"] for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
