"""Downloads the drawings people sent from the web page into samples/reports/.

    uv run python tools/pull_reports.py            # from Cloudflare
    uv run python tools/pull_reports.py --local    # from `bin/serve`'s simulated storage
    uv run python tools/pull_reports.py --delete   # also remove them from Cloudflare afterwards
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "samples" / "reports"


def wrangler(*args, where):
    return subprocess.run(["npx", "wrangler", "kv", "key", *args, "--binding", "REPORTS", where],
                          cwd=ROOT, check=True, capture_output=True).stdout


def main():
    where = "--local" if "--local" in sys.argv else "--remote"
    keys = [k["name"] for k in json.loads(wrangler("list", where=where))]
    for key in sorted(k.removeprefix("info:") for k in keys if k.startswith("info:")):
        folder = OUT / key.replace(":", "-")
        if not folder.exists():
            info = json.loads(wrangler("get", f"info:{key}", where=where))
            folder.mkdir(parents=True)
            (folder / "info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
            (folder / Path(info["name"]).name).write_bytes(wrangler("get", f"file:{key}", where=where))
            print(f"{folder.relative_to(ROOT)}: {info['name']} {info['comment']!r}")
        if "--delete" in sys.argv:
            for prefix in ("info:", "file:"):
                wrangler("delete", f"{prefix}{key}", where=where)


if __name__ == "__main__":
    main()
