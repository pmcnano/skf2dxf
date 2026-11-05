"""Collects hatch patterns stored in archive drawings into patterns.json, for drawings that
use one without storing it. AutoCAD's own patterns are skipped: ezdxf ships those.

    uv run python tools/build_pattern_library.py samples/batch
"""
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ezdxf.tools.pattern import IMPERIAL_PATTERN

import skf2dxf

OUT = Path(__file__).parent.parent / "patterns.json"


def stored_patterns(path):
    try:
        return skf2dxf.parse_hatch_styles(path.read_bytes())
    except Exception:
        return {}


def rounded(lines):
    return [[round(angle, 6), [round(v, 6) for v in base], [round(v, 6) for v in offset],
             [round(v, 6) for v in dashes]] for angle, base, offset, dashes in lines]


def main():
    files = [p for arg in sys.argv[1:] for p in Path(arg).rglob("*") if p.suffix.lower() == ".skf"]
    variants = defaultdict(Counter)
    with ProcessPoolExecutor() as pool:
        for patterns in pool.map(stored_patterns, files, chunksize=16):
            for name, lines in patterns.items():
                if name not in IMPERIAL_PATTERN and name not in skf2dxf.BUILTIN_PATTERNS:
                    variants[name][json.dumps(rounded(lines))] += 1
    # The most common definition wins when drawings disagree
    library = {name: json.loads(counts.most_common(1)[0][0]) for name, counts in sorted(variants.items())}
    OUT.write_text(json.dumps(library, separators=(",", ":")))
    print(f"{len(library)} patterns, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
