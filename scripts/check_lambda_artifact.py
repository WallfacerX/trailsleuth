"""Import the built handler and SDK without checkout or installed-package fallback."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CHECK = """
import json
import os
import pathlib
import sys
from unittest.mock import patch
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import boto3
import botocore
import trailsleuth.ingestion as ingestion
for module in (boto3, botocore, ingestion):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
assert callable(ingestion.handler)
event = {'Records': [{'messageId': 'synthetic-message', 'eventSource': 'aws:sqs',
    'body': json.dumps({'Service': 'Amazon S3', 'Event': 's3:TestEvent',
                        'Bucket': 'synthetic-input'})}]}
os.environ['INPUT_BUCKET'] = 'synthetic-input'
os.environ['RESULTS_BUCKET'] = 'synthetic-results'
with patch('boto3.client', return_value=object()):
    result = ingestion.handler(event, None)
assert result == {'batchItemFailures': []}
print('Packaged handler and SDK imported in isolation; test notification passed.')
"""


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Run artifact verification with Python 3.12 (the Lambda runtime).")
    with tempfile.TemporaryDirectory(prefix="trailsleuth-artifact-") as directory:
        with ZipFile(ROOT / "build" / "lambda" / "ingestion.zip") as archive:
            archive.extractall(directory)
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("AWS_", "PYTHON"))
        }
        subprocess.run(
            [sys.executable, "-I", "-S", "-c", CHECK, directory],
            cwd=directory,
            env=environment,
            check=True,
        )


if __name__ == "__main__":
    main()
