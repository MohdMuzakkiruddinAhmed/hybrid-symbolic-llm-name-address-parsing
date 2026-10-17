"""Regenerate analysis from released response banks, without provider calls."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(script, *args):
    subprocess.run([sys.executable, str(ROOT / "scripts/run_without_wmi.py"), str(ROOT / "scripts" / script), *args], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true", help="Also regenerate all 294 saved-bank policy evaluations")
    args = parser.parse_args()
    run("verify_release.py")
    if args.replay:
        run("evaluate_replay.py", "--split", "final", "--streams")
    run("analyze_study.py")
    run("analyze_followups.py")
    run("verify_release.py")


if __name__ == "__main__":
    main()
