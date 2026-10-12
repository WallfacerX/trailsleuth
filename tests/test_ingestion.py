import gzip
import io
import json
import socket
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote_plus

import pytest

from trailsleuth.ingestion import (
    IngestionConfig,
    IngestionError,
    process_batch,
    result_key,
)

CONFIG = IngestionConfig("synthetic-input", "synthetic-results")
KEY = "incoming/events.json"
VERSION = "synthetic-version-1"
DATA = (Path(__file__).resolve().parents[1] / "sample_data/cloudtrail_events.json").read_bytes()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Ingestion tests must not access the network")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


class Body(io.BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class FakeS3:
    def __init__(self):
        self.objects = {(KEY, VERSION): DATA}
        self.results = {}
        self.gets = []
        self.puts = []
        self.bodies = []
        self.read_failures = set()
        self.write_failures = set()
        self.fail_after_write = False
        self.response_overrides = {}

    def get_object(self, **kwargs):
        self.gets.append(kwargs)
        assert kwargs["Bucket"] == CONFIG.input_bucket
        source = (kwargs["Key"], kwargs["VersionId"])
        if source in self.read_failures:
            raise RuntimeError("untrusted exception text must not reach logs")
        data = self.objects[source]
        body = Body(data)
        self.bodies.append(body)
        return {
            "Body": body,
            "VersionId": source[1],
            "ContentLength": len(data),
            **self.response_overrides,
        }

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        assert kwargs["Bucket"] == CONFIG.results_bucket
        assert kwargs["ContentType"] == "application/json"
        assert kwargs["ServerSideEncryption"] == "AES256"
        if kwargs["Key"] in self.write_failures:
            raise RuntimeError("synthetic write failure")
        self.results[kwargs["Key"]] = kwargs["Body"]
        if self.fail_after_write:
            raise RuntimeError("synthetic lost acknowledgement")
        return {}


def record(key=KEY, version=VERSION):
    return {
        "eventSource": "aws:s3",
        "eventName": "ObjectCreated:Put",
        "s3": {
            "bucket": {"name": CONFIG.input_bucket},
            "object": {"key": quote_plus(key), "versionId": version},
        },
    }


def message(message_id="message-1", records=None, notification=None):
    if notification is None:
        notification = {"Records": [record()] if records is None else records}
    return {"messageId": message_id, "eventSource": "aws:sqs", "body": json.dumps(notification)}


def run(s3, messages=None, config=CONFIG):
    return process_batch({"Records": messages or [message()]}, s3=s3, config=config)


def assert_failed(response, *ids):
    assert response == {"batchItemFailures": [{"itemIdentifier": value} for value in ids]}


@pytest.mark.parametrize("compressed", [False, True])
def test_json_and_gzip_preserve_evidence_and_rules(compressed):
    s3 = FakeS3()
    if compressed:
        # Gzip magic is recognized even without a .gz extension.
        s3.objects[(KEY, VERSION)] = gzip.compress(DATA)
    assert_failed(run(s3))
    output = json.loads(next(iter(s3.results.values())))
    assert output["source"] == {"bucket": CONFIG.input_bucket, "key": KEY, "version_id": VERSION}
    assert output["mode"] == "rule-based"
    assert output["schema_version"] == 1
    assert len(output["normalized_events"]) == 5
    assert [finding["rule_id"] for finding in output["findings"]] == ["TS-001", "TS-002"]
    original = json.loads(DATA)["Records"]
    assert [event["event_id"] for event in output["normalized_events"]] == [
        event["eventID"] for event in original
    ]
    assert all(f"versionId={VERSION}" in item["source_reference"] for item in output["findings"])
    assert output["normalized_events"][4]["error_code"] == "AccessDenied"
    assert s3.gets == [{"Bucket": CONFIG.input_bucket, "Key": KEY, "VersionId": VERSION}]
    assert s3.bodies[0].closed


@pytest.mark.parametrize(
    "key", ["incoming/a b+c.json", "incoming/雪/%2F.json", "incoming/file.json.gz"]
)
def test_keys_are_decoded_exactly_once(key):
    s3 = FakeS3()
    s3.objects[(key, VERSION)] = gzip.compress(DATA) if key.endswith(".gz") else DATA
    assert_failed(run(s3, [message(records=[record(key)])]))
    assert s3.gets[0]["Key"] == key
    output = json.loads(next(iter(s3.results.values())))
    assert output["source"]["key"] == key


def test_multiple_records_and_partial_completion_recovery():
    s3 = FakeS3()
    other = "incoming/other.json"
    s3.objects[(other, VERSION)] = DATA
    s3.read_failures.add((KEY, VERSION))
    messages = [message(records=[record(), record(other)])]
    assert_failed(run(s3, messages), "message-1")
    other_key = result_key(CONFIG.input_bucket, other, VERSION)
    assert list(s3.results) == [other_key]  # A later record was still processed.
    previous = s3.results[other_key]
    s3.read_failures.clear()
    assert_failed(run(s3, messages))
    assert len(s3.results) == 2
    assert s3.results[other_key] == previous
    assert sum(item["Key"] == other_key for item in s3.puts) == 2


def test_s3_test_notification_does_not_access_s3():
    notification = {"Service": "Amazon S3", "Event": "s3:TestEvent", "Bucket": CONFIG.input_bucket}
    s3 = FakeS3()
    assert_failed(run(s3, [message(notification=notification)]))
    assert not s3.gets and not s3.puts


def test_mixed_success_and_failures():
    s3 = FakeS3()
    messages = [
        message("good"),
        message("bad", records=[record(version=None)]),
        message("also-good"),
    ]
    assert_failed(run(s3, messages), "bad")
    assert len(s3.results) == 1


@pytest.mark.parametrize("version", [None, "", "null", 123])
def test_immutable_version_required(version):
    s3 = FakeS3()
    assert_failed(run(s3, [message(records=[record(version=version)])]), "message-1")
    assert not s3.gets


def test_missing_version_and_unexpected_source():
    for change in ("version", "bucket", "prefix", "event"):
        item = record()
        if change == "version":
            del item["s3"]["object"]["versionId"]
        elif change == "bucket":
            item["s3"]["bucket"]["name"] = "other-bucket"
        elif change == "prefix":
            item["s3"]["object"]["key"] = "elsewhere/events.json"
        else:
            item["eventName"] = "ObjectRemoved:Delete"
        s3 = FakeS3()
        assert_failed(run(s3, [message(records=[item])]), "message-1")
        assert not s3.gets


@pytest.mark.parametrize(
    "notification",
    [
        None,
        [],
        {},
        {"Records": []},
        {"Records": [None]},
        {
            "Service": "wrong",
            "Event": "s3:TestEvent",
            "Bucket": CONFIG.input_bucket,
        },
    ],
)
def test_malformed_notifications(notification):
    item = message()
    item["body"] = json.dumps(notification)
    assert_failed(run(FakeS3(), [item]), "message-1")


def test_malformed_message_body():
    item = message()
    item["body"] = "not-json"
    assert_failed(run(FakeS3(), [item]), "message-1")


@pytest.mark.parametrize(
    "data",
    [
        b"{",
        b"\xff",
        b'{"Records": [1]}',
        b'{"Records": NaN}',
        gzip.compress(DATA)[:-5],
        b"\x1f\x8bnot-gzip",
    ],
)
def test_invalid_data_retries_and_closes_body(data):
    s3 = FakeS3()
    s3.objects[(KEY, VERSION)] = data
    assert_failed(run(s3), "message-1")
    assert not s3.puts
    assert s3.bodies[0].closed


def test_gzip_suffix_requires_valid_gzip():
    s3 = FakeS3()
    key = "incoming/bad.gz"
    s3.objects[(key, VERSION)] = DATA
    assert_failed(run(s3, [message(records=[record(key)])]), "message-1")


def test_download_limit_uses_header_and_bounded_read():
    config = IngestionConfig(CONFIG.input_bucket, CONFIG.results_bucket, max_compressed_bytes=10)
    s3 = FakeS3()
    assert_failed(run(s3, config=config), "message-1")
    assert s3.bodies[0].read_sizes == []
    assert s3.bodies[0].closed
    s3.response_overrides["ContentLength"] = 10  # A misleading header cannot bypass the limit.
    assert_failed(run(s3, config=config), "message-1")
    assert s3.bodies[-1].read_sizes == [11]
    assert s3.bodies[-1].closed
    assert not s3.puts


@pytest.mark.parametrize("compressed", [False, True])
def test_decompressed_limit(compressed):
    s3 = FakeS3()
    s3.objects[(KEY, VERSION)] = gzip.compress(DATA) if compressed else DATA
    config = IngestionConfig(CONFIG.input_bucket, CONFIG.results_bucket, max_decompressed_bytes=100)
    assert_failed(run(s3, config=config), "message-1")
    assert not s3.puts


def test_exact_size_boundary_is_accepted():
    config = IngestionConfig(CONFIG.input_bucket, CONFIG.results_bucket, len(DATA), len(DATA))
    assert_failed(run(FakeS3(), config=config))


@pytest.mark.parametrize("overrides", [{"ContentLength": len(DATA) + 1}, {"VersionId": "wrong"}])
def test_incomplete_download_or_wrong_version(overrides):
    s3 = FakeS3()
    s3.response_overrides = overrides
    assert_failed(run(s3), "message-1")
    assert not s3.puts
    assert s3.bodies[0].closed


def test_read_failure_is_retried_and_logs_do_not_dump_data(caplog):
    s3 = FakeS3()
    s3.read_failures.add((KEY, VERSION))
    assert_failed(run(s3), "message-1")
    assert not s3.puts
    s3.read_failures.clear()
    assert_failed(run(s3))
    summaries = [json.loads(item.message) for item in caplog.records]
    assert any(item["status"] == "object_failed" for item in summaries)
    assert any(item.get("events") == 5 for item in summaries)
    assert "untrusted exception text" not in caplog.text
    assert "synthetic-analyst" not in caplog.text
    assert "sourceIPAddress" not in caplog.text


def test_write_failure_is_not_acknowledged():
    s3 = FakeS3()
    s3.write_failures.add(result_key(CONFIG.input_bucket, KEY, VERSION))
    assert_failed(run(s3), "message-1")
    assert not s3.results
    s3.write_failures.clear()
    assert_failed(run(s3))
    assert len(s3.results) == 1


def test_lost_write_acknowledgement_converges():
    s3 = FakeS3()
    s3.fail_after_write = True
    assert_failed(run(s3), "message-1")
    durable = deepcopy(s3.results)
    s3.fail_after_write = False
    assert_failed(run(s3))
    assert s3.results == durable


def test_duplicates_stable_and_versions_distinct():
    s3 = FakeS3()
    assert_failed(run(s3))
    original = deepcopy(s3.results)
    assert_failed(run(s3, [message("different-delivery")]))
    assert s3.results == original
    s3.objects[(KEY, "synthetic-version-2")] = DATA
    assert_failed(run(s3, [message(records=[record(version="synthetic-version-2")])]))
    assert len(s3.results) == 2
    assert len(s3.puts) == 3  # Repeated computation is intentional.
    assert result_key("a", "bc", "d") != result_key("ab", "c", "d")


@pytest.mark.parametrize("event", [None, {}, {"Records": [None]}, {"Records": [{"messageId": ""}]}])
def test_invalid_outer_envelope_fails_invocation(event):
    with pytest.raises(IngestionError):
        process_batch(event, s3=FakeS3(), config=CONFIG)


def test_empty_batch_and_duplicate_message_ids():
    assert_failed(process_batch({"Records": []}, s3=FakeS3(), config=CONFIG))
    with pytest.raises(IngestionError, match="duplicate_sqs_message_id"):
        run(FakeS3(), [message(), message()])
