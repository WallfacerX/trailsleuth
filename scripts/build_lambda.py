"""Build a deterministic ZIP with Linux ARM64-compatible Python 3.12 dependencies."""

import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "lambda"


def main() -> None:
    staging = BUILD / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-compile",
            "--no-deps",
            "--only-binary=:all:",
            "--platform",
            "manylinux2014_aarch64",
            "--python-version",
            "3.12",
            "--implementation",
            "cp",
            "--abi",
            "cp312",
            "--target",
            str(staging),
            "-r",
            str(ROOT / "requirements-lambda.txt"),
        ],
        check=True,
    )
    shutil.copytree(
        ROOT / "src" / "trailsleuth",
        staging / "trailsleuth",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(ROOT / "LICENSE", staging / "TRAILSLEUTH_LICENSE")
    artifact = BUILD / "ingestion.zip"
    temporary = BUILD / "ingestion.zip.tmp"
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(staging)
            if "__pycache__" in relative.parts or relative.parts[0] == "bin":
                continue
            info = ZipInfo(relative.as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    temporary.replace(artifact)
    print(f"Built {artifact}")


if __name__ == "__main__":
    main()
