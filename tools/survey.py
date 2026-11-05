"""Flags drawings that need a closer look: crashes, skipped or unknown items, misread records.

    uv run python tools/survey.py samples/batch [--csv tmp/survey.csv]

Identical files are surveyed once. The summary groups results by AutoSketch version.
"""
import csv
import hashlib
import sys
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import skf2dxf

# Bytes left after a record is decoded; anything else means the record was misread
EXPECTED_LEFTOVER = {1: 8, 8: 4, 19: 5}


def version(data):
    """AutoSketch's header: u32 10, two bytes, then format id, version, build and date."""
    try:
        if not data.startswith(b"\x0a\x00\x00\x00"):
            raise ValueError
        r = skf2dxf.Reader(data, 6)
        return f"{r.pstr()} v{r.pstr()}"
    except (ValueError, IndexError):
        return "unrecognized"


def misread(data):
    symbols, entities = skf2dxf.parse(data)
    found = Counter()

    def walk(ents):
        for e in ents:
            if e["type"] in skf2dxf.PARSERS and e["left"] != EXPECTED_LEFTOVER.get(e["type"], 0):
                found[f"misread {skf2dxf.ENTITY_NAMES[e['type']]}"] += 1
            walk(e.get("children", []))

    walk(entities)
    for ents in symbols.values():
        walk(ents)
    return found


def survey(path):
    data = Path(path).read_bytes()
    try:
        _, report = skf2dxf.to_dxf(data)
        issues = Counter({k: v for k, v in report.items() if skf2dxf.is_warning(k)})
        issues.update(misread(data))
    except skf2dxf.SkfError as error:
        issues = Counter({f"rejected: {error}": 1})
    except Exception as error:
        where = traceback.extract_tb(error.__traceback__)[-1]
        issues = Counter({f"crash: {type(error).__name__} in {where.name}": 1})
    return path, version(data), issues


def main():
    args = sys.argv[1:]
    csv_path = None
    if "--csv" in args:
        csv_path = args.pop(args.index("--csv") + 1)
        args.remove("--csv")
    files = sorted(p for arg in args for p in Path(arg).rglob("*")
                   if p.is_file() and p.suffix.lower() in (".skf", ".skd"))
    unique = {}
    for path in files:
        unique.setdefault(hashlib.sha1(path.read_bytes()).hexdigest(), str(path))
    print(f"{len(files)} files, {len(unique)} unique", file=sys.stderr)

    totals, clean = Counter(), Counter()
    by_issue = defaultdict(Counter)  # version -> issue -> files
    examples = {}
    rows = []
    with ProcessPoolExecutor() as pool:
        for done, (path, ver, issues) in enumerate(
                pool.map(survey, unique.values(), chunksize=8), 1):
            totals[ver] += 1
            clean[ver] += not issues
            for issue in issues:
                by_issue[ver][issue] += 1
                examples.setdefault((ver, issue), path)
            rows.append((path, ver, "; ".join(f"{v} {k}" for k, v in sorted(issues.items()))))
            if done % 500 == 0:
                print(f"  {done}/{len(unique)}", file=sys.stderr)

    for ver in sorted(totals, key=totals.get, reverse=True):
        print(f"\n{ver}: {clean[ver]} of {totals[ver]} converted with nothing to report")
        for issue, count in by_issue[ver].most_common(15):
            print(f"  {count:6} files  {issue}")
            print(f"                e.g. {examples[(ver, issue)]}")
    if csv_path:
        with open(csv_path, "w", newline="") as f:
            csv.writer(f).writerows([("path", "version", "issues"), *rows])


if __name__ == "__main__":
    main()
