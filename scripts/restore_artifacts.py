"""Restore checksummed study archives without making network or model calls."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def restore(path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("archive checksum mismatch: " + path.name)
    files = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename:
                raise ValueError("unsafe archive member")
            target = ROOT.joinpath(*name.parts).resolve()
            if not target.is_relative_to(ROOT) or target == ROOT:
                raise ValueError("archive path escapes repository")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Exact archive content replaces only versioned data/results paths.
            if name.parts[0] not in ("data", "results", "annotation"):
                raise ValueError("unexpected archive root")
            with archive.open(info) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            files += 1
    print(json.dumps({"archive": path.name, "restored_files": files, "provider_calls": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-only", action="store_true")
    parser.add_argument("--results", type=Path, help="Path to the separately downloaded results ZIP")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "artifacts/manifest.json").read_text(encoding="utf-8"))
    dataset = manifest["dataset"]
    restore(ROOT / "artifacts" / dataset["filename"], dataset["sha256"])
    if args.dataset_only:
        return
    results = manifest["results"]
    candidates = [args.results] if args.results else [ROOT / "artifacts" / results["filename"], ROOT.parent / "release-assets" / results["filename"]]
    path = next((p for p in candidates if p and p.is_file()), None)
    if path is None:
        raise SystemExit("Dataset restored. Download " + results["filename"] + " from the GitHub release, place it in artifacts/, then rerun this command.")
    restore(path, results["sha256"])


if __name__ == "__main__":
    main()
