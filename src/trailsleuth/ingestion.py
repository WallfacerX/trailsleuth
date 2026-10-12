"""Version-aware SQS/S3 ingestion. AWS access is injected into the processing core."""

import gzip
import hashlib
import io
import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote, unquote_plus

from trailsleuth.detection import detect
from trailsleuth.normalization import EventValidationError, normalize_events

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
MAX_COMPRESSED_BYTES = 5 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 20 * 1024 * 1024


class IngestionError(ValueError):
    """An expected ingestion failure with a safe, fixed log category."""


@dataclass(frozen=True)
class IngestionConfig:
    input_bucket: str
    results_bucket: str
    max_compressed_bytes: int = MAX_COMPRESSED_BYTES
    max_decompressed_bytes: int = MAX_DECOMPRESSED_BYTES

    def __post_init__(self) -> None:
        if not self.input_bucket or not self.results_bucket:
            raise ValueError("Input and results bucket names are required")
        if self.input_bucket == self.results_bucket:
            raise ValueError("Input and results buckets must be different")
        if self.max_compressed_bytes < 1 or self.max_decompressed_bytes < 1:
            raise ValueError("Size limits must be positive")


def result_key(bucket: str, key: str, version: str) -> str:
    """One output key per immutable source version, independent of delivery metadata."""
    source = json.dumps([bucket, key, version], ensure_ascii=True, separators=(",", ":"))
    return f"results/v1/{hashlib.sha256(source.encode('utf-8')).hexdigest()}.json"


def _reject_constant(value: str) -> None:
    raise IngestionError("invalid_json_constant")


def _json(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def _summary(status: str, **fields: Any) -> None:
    LOGGER.info(json.dumps({"status": status, **fields}, sort_keys=True))


def _category(exc: Exception) -> str:
    # Never log exception text: parsers and SDK errors may echo untrusted content.
    if isinstance(exc, IngestionError):
        return str(exc)
    if isinstance(exc, EventValidationError):
        return "invalid_cloudtrail"
    if isinstance(exc, (json.JSONDecodeError, UnicodeError)):
        return "invalid_json"
    if isinstance(exc, (gzip.BadGzipFile, EOFError)):
        return "invalid_gzip"
    return "processing_or_aws_error"


def _source(record: object, config: IngestionConfig) -> tuple[str, str, str]:
    if not isinstance(record, dict):
        raise IngestionError("invalid_s3_record")
    if record.get("eventSource") != "aws:s3" or not str(record.get("eventName", "")).startswith(
        "ObjectCreated:"
    ):
        raise IngestionError("unexpected_s3_event")
    try:
        bucket = record["s3"]["bucket"]["name"]
        encoded_key = record["s3"]["object"]["key"]
        version = record["s3"]["object"].get("versionId")
    except (KeyError, TypeError, AttributeError) as exc:
        raise IngestionError("invalid_s3_record") from exc
    if bucket != config.input_bucket or not isinstance(encoded_key, str):
        raise IngestionError("unexpected_source")
    key = unquote_plus(encoded_key, encoding="utf-8", errors="strict")
    if not key.startswith("incoming/") or key == "incoming/":
        raise IngestionError("unexpected_prefix")
    if not isinstance(version, str) or not version.strip() or version == "null":
        raise IngestionError("immutable_version_required")
    return bucket, key, version


def _read_object(s3: Any, config: IngestionConfig, bucket: str, key: str, version: str) -> Any:
    response = s3.get_object(Bucket=bucket, Key=key, VersionId=version)
    body = response["Body"]
    try:
        if response.get("VersionId") != version:
            raise IngestionError("source_version_mismatch")
        length = response.get("ContentLength")
        if length is not None and (
            not isinstance(length, int) or length < 0 or length > config.max_compressed_bytes
        ):
            raise IngestionError("download_size_limit")
        data = body.read(config.max_compressed_bytes + 1)
        if len(data) > config.max_compressed_bytes:
            raise IngestionError("download_size_limit")
        if length is not None and len(data) != length:
            raise IngestionError("incomplete_download")
    finally:
        body.close()
    if data.startswith(b"\x1f\x8b") or key.lower().endswith(".gz"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            data = compressed.read(config.max_decompressed_bytes + 1)
    if len(data) > config.max_decompressed_bytes:
        raise IngestionError("decompressed_size_limit")
    return _json(data.decode("utf-8"))


def _process_record(record: object, s3: Any, config: IngestionConfig) -> dict[str, Any]:
    bucket, key, version = _source(record, config)
    payload = _read_object(s3, config, bucket, key, version)
    reference = f"s3://{bucket}/{quote(key, safe='/')}?versionId={quote(version, safe='')}"
    events = normalize_events(payload, source_reference=reference)
    findings = detect(events)
    output_key = result_key(bucket, key, version)
    output = {
        "schema_version": 1,
        "mode": "rule-based",
        "source": {"bucket": bucket, "key": key, "version_id": version},
        "normalized_events": [asdict(event) for event in events],
        "findings": [asdict(finding) for finding in findings],
    }
    s3.put_object(
        Bucket=config.results_bucket,
        Key=output_key,
        Body=json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )
    return {"result_key": output_key, "events": len(events), "findings": len(findings)}


def process_batch(event: object, *, s3: Any, config: IngestionConfig) -> dict[str, Any]:
    """Acknowledge a message only after all its object outputs are durable.

    Exceptions are caught at message/record boundaries for partial batch replies.
    Invalid outer envelopes cannot be safely acknowledged and fail the invocation.
    """
    if not isinstance(event, dict) or not isinstance(event.get("Records"), list):
        raise IngestionError("invalid_sqs_envelope")
    messages = event["Records"]
    ids = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or not isinstance(message.get("messageId"), str)
            or not message["messageId"].strip()
        ):
            raise IngestionError("invalid_sqs_message_id")
        ids.append(message["messageId"])
    if len(ids) != len(set(ids)):
        raise IngestionError("duplicate_sqs_message_id")
    failed = []
    for message in messages:
        message_id = message["messageId"]
        try:
            if message.get("eventSource") != "aws:sqs" or not isinstance(message.get("body"), str):
                raise IngestionError("invalid_sqs_message")
            notification = _json(message["body"])
            if not isinstance(notification, dict):
                raise IngestionError("invalid_s3_notification")
            if notification.get("Event") == "s3:TestEvent":
                if (
                    notification.get("Service") != "Amazon S3"
                    or notification.get("Bucket") != config.input_bucket
                ):
                    raise IngestionError("invalid_test_notification")
                _summary("test_notification", message_id=message_id)
                continue
            records = notification.get("Records")
            if not isinstance(records, list) or not records:
                raise IngestionError("invalid_s3_notification")
            message_failed = False
            for index, record in enumerate(records):
                try:
                    summary = _process_record(record, s3, config)
                    _summary("object_written", message_id=message_id, record_index=index, **summary)
                except Exception as exc:
                    message_failed = True
                    _summary(
                        "object_failed",
                        message_id=message_id,
                        record_index=index,
                        category=_category(exc),
                    )
            if message_failed:
                failed.append({"itemIdentifier": message_id})
        except Exception as exc:
            failed.append({"itemIdentifier": message_id})
            _summary("message_failed", message_id=message_id, category=_category(exc))
    _summary("batch_complete", messages=len(messages), failed_messages=len(failed))
    return {"batchItemFailures": failed}


def handler(event: object, context: object) -> dict[str, Any]:
    """AWS Lambda entry point; importing this module never creates an AWS client."""
    import boto3
    from botocore.config import Config

    config = IngestionConfig(
        input_bucket=os.environ["INPUT_BUCKET"], results_bucket=os.environ["RESULTS_BUCKET"]
    )
    s3 = boto3.client(
        "s3", config=Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2})
    )
    return process_batch(event, s3=s3, config=config)
