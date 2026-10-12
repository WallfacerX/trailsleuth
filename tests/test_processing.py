import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from trailsleuth.cli import main
from trailsleuth.detection import detect
from trailsleuth.normalization import EventValidationError, normalize_events

FIXTURE = Path(__file__).resolve().parents[1] / "sample_data/cloudtrail_events.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


def test_fixture_findings_and_provenance(payload):
    events = normalize_events(payload, source_reference="s3://synthetic-bucket/events.json")
    findings = detect(events)
    assert len(events) == 5
    assert [(f.rule_id, f.severity) for f in findings] == [("TS-001", "high"), ("TS-002", "medium")]
    assert [f.event_id for f in findings] == [events[2].event_id, events[3].event_id]
    assert all(f.source_reference == "s3://synthetic-bucket/events.json" for f in findings)
    assert all(
        "legitimate" in f.reason and "does not prove compromise" in f.reason for f in findings
    )
    event = events[4]
    raw = payload["Records"][4]
    assert (event.timestamp, event.source, event.action, event.region, event.source_ip) == (
        raw["eventTime"],
        raw["eventSource"],
        raw["eventName"],
        raw["awsRegion"],
        raw["sourceIPAddress"],
    )
    assert event.identity == raw["userIdentity"]
    assert (event.error_code, event.error_message) == (raw["errorCode"], raw["errorMessage"])
    raw["userIdentity"]["userName"] = "changed"
    assert event.identity["userName"] == "synthetic-analyst"


def test_optional_fields_and_empty_input(payload):
    raw = payload["Records"][2]
    required = {k: raw[k] for k in ("eventID", "eventTime", "eventSource", "eventName")}
    event = normalize_events({"Records": [required]}, source_reference="fixture")[0]
    assert event.region is event.identity is event.source_ip is None
    assert event.error_code is event.error_message is None
    assert len(detect([event])) == 1
    assert normalize_events({"Records": []}, source_reference="fixture") == []


@pytest.mark.parametrize("payload", [None, [], {}, {"Records": {}}, {"Records": [None]}])
def test_bad_envelopes(payload):
    with pytest.raises(EventValidationError, match="fixture.*Records"):
        normalize_events(payload, source_reference="fixture")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("eventID", None),
        ("eventID", " "),
        ("eventSource", 12),
        ("eventName", ""),
        ("eventTime", "not-a-time"),
        ("eventTime", "2026-01-01T00:00:00"),
        ("eventTime", "2026-02-30T00:00:00Z"),
        ("userIdentity", []),
        ("awsRegion", 1),
        ("sourceIPAddress", {}),
        ("errorCode", False),
        ("errorMessage", []),
    ],
)
def test_bad_fields_have_context(payload, field, value):
    payload["Records"][0][field] = value
    with pytest.raises(EventValidationError, match=rf"fixture: Records\[0\].{field}"):
        normalize_events(payload, source_reference="fixture")


@pytest.mark.parametrize("index", [2, 3])
@pytest.mark.parametrize("errors", [{"errorCode": "AccessDenied"}, {"errorMessage": "Denied"}])
def test_any_error_suppresses_success(payload, index, errors):
    record = deepcopy(payload["Records"][index])
    record.update(errors)
    assert detect(normalize_events({"Records": [record]}, source_reference="fixture")) == []


@pytest.mark.parametrize("index", [2, 3])
def test_source_and_action_must_both_match(payload, index):
    record = payload["Records"][index]
    record["eventSource"] = "unrelated.amazonaws.com"
    assert detect(normalize_events({"Records": [record]}, source_reference="fixture")) == []


def test_null_optionals_and_service_source_ip(payload):
    record = payload["Records"][2]
    record.update(userIdentity=None, awsRegion=None, errorCode=None, errorMessage=None)
    record["sourceIPAddress"] = "cloudtrail.amazonaws.com"
    event = normalize_events({"Records": [record]}, source_reference="fixture")[0]
    assert event.source_ip == "cloudtrail.amazonaws.com"
    assert len(detect([event])) == 1


def test_invalid_provenance(payload):
    with pytest.raises(EventValidationError, match="source_reference"):
        normalize_events(payload, source_reference="")


def test_cli_json_is_stable(capsys):
    assert main(["detect", str(FIXTURE)]) == 0
    first = capsys.readouterr()
    assert main(["detect", str(FIXTURE)]) == 0
    assert capsys.readouterr().out == first.out
    output = json.loads(first.out)
    assert output["mode"] == "rule-based"
    assert output["processed_events"] == 5
    assert len(output["findings"]) == 2
    assert first.err == ""


@pytest.mark.parametrize("contents", ['{"Records":', '{"Records": [123]}', "\xff"])
def test_cli_bad_input(tmp_path, capsys, contents):
    path = tmp_path / "bad.json"
    path.write_bytes(contents.encode("latin-1"))
    assert main(["detect", str(path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert str(path) in output.err


def test_cli_missing_file(tmp_path, capsys):
    assert main(["detect", str(tmp_path / "absent.json")]) == 2
    assert "absent.json" in capsys.readouterr().err


def test_cli_validates_whole_file_before_output(payload, tmp_path, capsys):
    payload["Records"].append({})
    path = tmp_path / "partial.json"
    path.write_text(json.dumps(payload))
    assert main(["detect", str(path)]) == 2
    assert capsys.readouterr().out == ""


def test_module_entrypoint_without_aws_credentials():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
    result = subprocess.run(
        [sys.executable, "-m", "trailsleuth", "detect", str(FIXTURE)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["findings"]) == 2
