#!/usr/bin/env python3
"""Offline contracts. HTTP and request execution are always mocked."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("sightengine_diagnostic", Path(__file__).with_name("eval-sightengine-api.py"))
M = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)


def case(order=1):
    return {"order": order, "id": "case-" + str(order), "sourceLabel": "mixed" if order == 2 else "ai" if order == 1 else "cgi",
            "expectedPrimaryDecision": "ai" if order < 3 else "not_ai",
            "media": {"durationSeconds": 8 if order < 5 else 5}}


def response(c, score=None):
    frames = []
    for i in range(int(c["media"]["durationSeconds"] * 2)):
        p = i / 2
        value = score if score is not None else .9 if c["order"] == 1 or c["order"] == 2 and 3 <= p < 5 else .1
        frames.append({"info": {"position": i * 500}, "type": {"ai_generated": value}})
    return {"status": "success", "request": {"id": "safe-id", "timestamp": 1800000000, "operations": len(frames) * 5},
            "data": {"frames": frames}}


def parse(value, c=None, secrets=()):
    return M.parse_response(json.dumps(value).encode(), c or case(), secrets)


class Parsing(unittest.TestCase):
    def test_fixed_millisecond_mapping_and_threshold(self):
        c = case(2); result = parse(response(c), c)
        self.assertTrue(result["coverageComplete"]); self.assertTrue(result["mixedLocalizationPass"])
        self.assertEqual(result["frames"][6]["rawPositionMilliseconds"], 3000)
        self.assertEqual(result["frames"][6]["positionSeconds"], 3)
        self.assertEqual(result["primaryDecision"], "ai")
        self.assertEqual(parse(response(case(), .5))["primaryDecision"], "ai")
        self.assertEqual(parse(response(case(), .49999))["primaryDecision"], "not_ai")

    def test_no_automatic_seconds_unit_fallback(self):
        value = response(case())
        for f in value["data"]["frames"]:
            f["info"]["position"] /= 1000
        result = parse(value)
        self.assertFalse(result["coverageComplete"]); self.assertIsNone(result["primaryDecision"])

    def test_missing_invalid_nonfinite_and_unknown_schema(self):
        for value in ({}, {"status": "failure", "error": "secret"}, {"status": "success"}):
            self.assertIsNone(parse(value)["primaryDecision"])
        for bad in (None, True, "0.9", -1, 1.1, float("nan"), float("inf")):
            value = response(case()); value["data"]["frames"][2]["type"]["ai_generated"] = bad
            result = parse(value); self.assertFalse(result["schemaValid"]); self.assertIsNone(result["primaryDecision"])
        self.assertIn("invalid_json", M.parse_response(b'{"status":"success","status":"failure"}', case())["issues"])

    def test_zero_and_missing_frames_never_negative(self):
        for frames in ([], None):
            value = response(case(3)); value["data"]["frames"] = frames
            self.assertIsNone(parse(value, case(3))["primaryDecision"])

    def test_missing_unknown_underreported_excess_operations(self):
        for ops in (None, True, -1, 0, 1, 79, 86, "80"):
            value = response(case()); value["request"]["operations"] = ops
            self.assertFalse(parse(value)["schemaValid"])
        value = response(case()); del value["request"]["operations"]
        self.assertIn("unknown_operations", parse(value)["issues"])

    def test_partial_duplicate_reversed_outside_coverage(self):
        for indexes in (list(range(1,16)), list(range(15)), [0,1,3,*range(4,16)], [0,0,*range(2,16)], [1,0,*range(2,16)]):
            value = response(case()); value["data"]["frames"] = [value["data"]["frames"][i] for i in indexes]
            value["request"]["operations"] = len(indexes) * 5
            result = parse(value); self.assertFalse(result["coverageComplete"])
            self.assertIsNone(result["primaryDecision"]); self.assertTrue(result["secondaryAnyPositive"])
        value = response(case()); value["data"]["frames"][-1]["info"]["position"] = 8000
        self.assertFalse(parse(value)["schemaValid"])

    def test_mixed_boundary_and_outside_positive_fail_localization(self):
        for position in (0, 2500, 5000, 7500):
            value = response(case(2)); value["data"]["frames"][position//500]["type"]["ai_generated"] = .8
            result = parse(value, case(2))
            self.assertEqual(result["primaryDecision"], "ai"); self.assertFalse(result["mixedLocalizationPass"])
        self.assertFalse(parse(response(case(2), .1), case(2))["mixedLocalizationPass"])

    def test_response_cap_and_secret_allowlist(self):
        self.assertIn("response_too_large", M.parse_response(b'x' * (1048576+1), case())["issues"])
        value = response(case()); value["api_secret"] = "do-not-save"; value["request"]["id"] = "echo-do-not-save"
        value["data"]["frames"][0]["extra"] = "do-not-save"
        result = parse(value, secrets=("do-not-save",)); dumped = json.dumps(result)
        self.assertNotIn("do-not-save", dumped); self.assertEqual(result["request"]["id"], "[redacted]")


class Execution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sightengine-offline-")
        self.root = Path(self.tmp.name).resolve(); (self.root / "eval").mkdir()
        self.root_patch = patch.object(M, "ROOT", self.root); self.root_patch.start()
        self.env = patch.dict(os.environ, {"SIGHTENGINE_API_USER": "synthetic-user", "SIGHTENGINE_API_SECRET": "synthetic-secret"}, clear=True); self.env.start()
        cases = []
        for i in range(1,6):
            c = case(i); data = ("synthetic media bytes " + str(i)).encode(); path = self.root / f"eval/clip{i}.mp4"; path.write_bytes(data)
            c.update(path=str(path.relative_to(self.root)), sha256=hashlib.sha256(data).hexdigest())
            c["media"]["bytes"] = len(data); cases.append(c)
        source = self.root / "eval/source.json"; source.write_text(json.dumps({"cases": cases}))
        self.source_patch = patch.object(M, "SOURCE", {"path": "eval/source.json", "sha256": M.sha(source)}); self.source_patch.start()
        fixture = {"schemaVersion": 1, "id": "sightengine-api-diagnostic-v1", "sourceFixture": M.SOURCE,
                   "api": M.API, "limits": M.LIMITS, "coverage": M.COVERAGE, "cases": cases,
                   "frozen": True, "frozenAt": "offline-test", "runnerSha256": M.sha(M.__file__)}
        self.fixture = self.root / "eval/fixture.json"; self.fixture.write_text(json.dumps(fixture))
        self.calls = []
        self.clock, self.sleeps = 0.0, []
        self.monotonic = patch.object(M.time,"monotonic",side_effect=lambda:self.clock);self.monotonic.start()
        def sleep(seconds):
            self.assertGreater(seconds,0);self.assertLessEqual(seconds,1)
            self.sleeps.append(seconds);self.clock+=seconds
        self.sleep = patch.object(M.time,"sleep",side_effect=sleep);self.sleep.start()

    def tearDown(self):
        self.sleep.stop();self.monotonic.stop()
        self.source_patch.stop(); self.env.stop(); self.root_patch.stop(); self.tmp.cleanup()

    def requester(self, fixture, c, ledger):
        self.assertTrue((self.root / ledger).is_file())
        self.assertEqual(json.loads((self.root / ledger).read_text())["requestNumber"], len(self.calls)+1)
        self.calls.append(c["order"])
        return {"kind": "response", "httpStatus": 200, "evidence": parse(response(c), c)}

    def run_study(self, requester=None, output="eval/run"):
        return M.run_study("eval/fixture.json", output, execute=True, requester=requester or self.requester)

    def test_preparation_is_network_free_and_rehashes_media(self):
        with patch.object(M.http.client, "HTTPSConnection", side_effect=AssertionError("network forbidden")):
            fixture, binding = M.validate_fixture("eval/fixture.json")
            self.assertEqual(binding["reservedNominalOperations"], 395)
            path = self.root / fixture["cases"][0]["path"]; path.write_bytes(b"changed")
            with self.assertRaises(ValueError): M.validate_fixture("eval/fixture.json")

    def test_five_ordered_once_and_global_rerun_refused(self):
        result = self.run_study(); self.assertTrue(result["diagnosticPass"])
        self.assertEqual(self.calls, [1,2,3,4,5]); self.assertEqual(result["reservedNominalOperations"], 395)
        self.assertEqual(result["reportedOperationsObserved"], 370)
        self.assertEqual(result["submissionIntents"], 5)
        self.assertEqual(self.sleeps,[1,1,1,1])
        starts=[json.loads((self.root/f"eval/run/{i:02d}.submitting.json").read_text())["monotonicIntentStart"] for i in range(1,6)]
        self.assertTrue(all(b-a>=1 for a,b in zip(starts,starts[1:])))
        with self.assertRaises(FileExistsError): self.run_study(output="eval/other-output")
        self.assertEqual(len(self.calls), 5)

    def test_wrong_classification_does_not_selectively_stop(self):
        def wrong(fixture,c,ledger):
            result = self.requester(fixture,c,ledger)
            if c["order"] == 1: result["evidence"] = parse(response(c,.1),c)
            return result
        result = self.run_study(wrong)
        self.assertEqual(self.calls, [1,2,3,4,5]); self.assertFalse(result["diagnosticPass"])
        self.assertIsNone(result["stopReason"])

    def test_pacing_is_after_completion_despite_variable_worker_delay(self):
        elapsed = [.9, .01, 2.1, .2, .01]
        def variable(fixture,c,ledger):
            self.clock += elapsed[c["order"]-1]
            return self.requester(fixture,c,ledger)
        result = self.run_study(variable)
        starts=[json.loads((self.root/f"eval/run/{i:02d}.submitting.json").read_text())["monotonicIntentStart"] for i in range(1,6)]
        completions=[r["monotonicRequesterCompletion"] for r in result["results"]]
        self.assertAlmostEqual(starts[1],1.9)
        self.assertTrue(all(start >= previous + 1 for start,previous in zip(starts[1:],completions)))
        self.assertTrue(result["diagnosticPass"])

    def test_transport_exception_stops_without_retry_and_retains_unknown(self):
        def fail(*args): self.calls.append(1); raise OSError("synthetic-secret")
        result = self.run_study(fail)
        self.assertEqual(self.calls, [1]); self.assertEqual(result["completedPredictions"], 0)
        self.assertEqual([r["status"] for r in result["results"]], ["no_result"] + ["not_attempted_due_to_stop"]*4)
        self.assertTrue(result["accountingMayBeIncomplete"])
        self.assertTrue(result["results"][0]["transmissionMayBeUncertain"])
        self.assertNotIn("synthetic-secret", json.dumps(result))

    def test_accounting_failure_stops_remainder(self):
        def wrong(fixture,c,ledger):
            self.calls.append(c["order"]); value=response(c); value["request"]["operations"] = 0
            return {"kind":"response", "evidence":parse(value,c)}
        result = self.run_study(wrong)
        self.assertEqual(self.calls,[1]); self.assertEqual(result["stopReason"],"schema_or_accounting_failure")
        self.assertTrue(result["accountingMayBeIncomplete"])

    def test_coverage_failure_preserves_secondary_but_stops(self):
        def gap(fixture,c,ledger):
            self.calls.append(c["order"]); value=response(c)
            del value["data"]["frames"][5]; value["request"]["operations"]-=5
            return {"kind":"response","evidence":parse(value,c)}
        result=self.run_study(gap)
        self.assertEqual(self.calls,[1]); self.assertEqual(result["stopReason"],"coverage_failure")
        self.assertTrue(result["results"][0]["response"]["evidence"]["secondaryAnyPositive"])
        self.assertIsNone(result["results"][0]["primaryDecision"])

    def test_explicit_flag_credentials_and_frozen_source_required(self):
        with self.assertRaises(ValueError): M.run_study("eval/fixture.json","eval/run",False,self.requester)
        with patch.dict(os.environ,{"SIGHTENGINE_API_SECRET":""}):
            with self.assertRaises(ValueError): self.run_study()
        value=json.loads(self.fixture.read_text()); value["runnerSha256"]="0"*64; self.fixture.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.run_study()
        self.assertEqual(self.calls,[])

    def test_actual_outbound_bytes_neutral_filename_and_tampering_guard(self):
        c=json.loads(self.fixture.read_text())["cases"][0]
        body,content_type=M.multipart(c,("synthetic-user","synthetic-secret"))
        self.assertIn(b'filename="clip-01.mp4"',body); self.assertNotIn(b'case-1',body)
        self.assertIn(b'name="models"\r\n\r\ngenai',body); self.assertIn(b'name="interval"\r\n\r\n0.5',body)
        (self.root/c["path"]).write_bytes(b"replaced after preflight")
        with self.assertRaises(ValueError): M.multipart(c,("synthetic-user","synthetic-secret"))

    def test_hard_timeout_passes_credentials_only_in_environment(self):
        with patch.object(M.subprocess,"run",side_effect=subprocess.TimeoutExpired("worker",180)) as process:
            result=M.execute_request("eval/fixture.json",case(),"eval/ledger.json")
        self.assertEqual(result["kind"],"wall_timeout")
        self.assertEqual(process.call_args.kwargs["timeout"],180)
        self.assertNotIn("synthetic-secret",repr(process.call_args.args))
        self.assertEqual(process.call_args.kwargs["env"]["SIGHTENGINE_API_SECRET"],"synthetic-secret")

    def test_http_refusal_no_redirect_or_second_request(self):
        fixture,binding=M.validate_fixture("eval/fixture.json",True); c=fixture["cases"][0]
        run=self.root/"eval/run";run.mkdir();(self.root/"eval/runs").mkdir()
        M.write_new(self.root/"eval/runs/sightengine-api-diagnostic-v1-execution.json",{"fixtureSha256":binding["fixtureSha256"],"outputPath":"eval/run"})
        M.write_new(run/"ledger.json",{"supervisorPid":os.getppid(),"status":"submitting","caseId":c["id"],"fixtureSha256":binding["fixtureSha256"],"mediaSha256":c["sha256"]})
        connection=Mock();connection.getresponse.return_value.status=302
        with patch.object(M.http.client,"HTTPSConnection",return_value=connection):
            result=M.remote_worker("eval/fixture.json",1,"eval/run/ledger.json")
        self.assertEqual(result,{"kind":"http_error","httpStatus":302,"operationsUnknown":True})
        self.assertEqual(connection.request.call_count,1);connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
