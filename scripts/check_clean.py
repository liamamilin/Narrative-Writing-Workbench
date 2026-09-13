"""Run tests from a source-only copy, without local settings or private data.

Includes new non-ignored source files so it also works before a commit.
Run with the test environment's Python: python scripts/check_clean.py
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATHS = ["app", "workbench", "tests", "prompts", "schemas", "scripts",
                "docs", ".github", "README.md", "AGENTS.md", "requirements*.txt",
                "config*.yaml"]


def main():
    files = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", *SOURCE_PATHS], cwd=ROOT).decode().split("\0")
    with tempfile.TemporaryDirectory(prefix="workbench-clean-") as directory:
        dest = Path(directory)
        for name in set(filter(None, files)):
            source = ROOT / name
            if not source.is_file():
                continue
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        print("Testing source-only copy (no private benchmarks/settings/database)", flush=True)
        for cmd in ([sys.executable, "-m", "pytest", "tests/", "-q"],
                    ["node", "--check", "workbench/static/app.js"]):
            result = subprocess.run(cmd, cwd=dest)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
