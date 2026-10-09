"""Verify that the approved frontend and business logic remain unchanged."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "docs/product-freeze.json").read_text())
paths = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *manifest["scope"]],
    cwd=ROOT,
).decode().split("\0")
actual = {
    name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    for name in set(paths) if name and (ROOT / name).is_file()
}
expected = manifest["files"]
changed = sorted(name for name in set(actual) | set(expected) if actual.get(name) != expected.get(name))
if changed:
    print("Product freeze violated; explicit user approval is required:")
    print("\n".join(changed))
    sys.exit(1)
print(f"Product freeze verified: {len(expected)} files match {manifest['baseline_commit']}.")
