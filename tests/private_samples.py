"""Real drawings can't be published, so samples/samples.json (gitignored) maps each role a test
needs to a file under samples/. Tests skip when their file isn't there."""
import json
from pathlib import Path

SAMPLES = Path(__file__).parent.parent / "samples"

try:
    MANIFEST = json.loads((SAMPLES / "samples.json").read_text())
except FileNotFoundError:
    MANIFEST = {}


def sample(role):
    return SAMPLES / MANIFEST.get(role, f"missing/{role}")
