import pytest

import skf2dxf
from private_samples import sample

# Bytes left after a record is decoded; anything else means the record was misread
EXPECTED_LEFTOVER = {1: 8, 8: 4, 19: 5}

# Drawings from an office's AutoSketch 7-10 archive, each kept for the case it covers
CASES = ["no symbol section", "symbol with data fields", "extra header fields 0x10 and 0x20",
         "named colors"]


def misread(entities):
    for e in entities:
        if e["type"] in skf2dxf.PARSERS and e["left"] != EXPECTED_LEFTOVER.get(e["type"], 0):
            yield e
        yield from misread(e.get("children", []))


@pytest.mark.parametrize("case", CASES)
def test_reads_archive_drawing(case):
    path = sample(case)
    if not path.exists():
        pytest.skip("archive samples missing")
    symbols, entities = skf2dxf.parse(path.read_bytes())
    assert entities
    assert not list(misread(entities))
    assert not [e for ents in symbols.values() for e in misread(ents)]


def test_named_colors_become_true_colors():
    path = sample("named rgb color")
    if not path.exists():
        pytest.skip("archive samples missing")
    doc, _ = skf2dxf.to_dxf(path.read_bytes())
    true_colors = {e.rgb for e in doc.modelspace() if e.dxf.hasattr("true_color")}
    # Stored in the drawing as color 152, "RGB(0,128,255)"
    assert (0, 128, 255) in true_colors
