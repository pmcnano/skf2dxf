import math

import pytest

import skf2dxf


def entity(etype, **fields):
    return {"type": etype, "layer": "0", "color": -1, "linetype": None, **fields}


def insert(name):
    return entity(14, name=name, insert=(0, 0), scale=(1, 1), rotation=0)


@pytest.fixture
def writer():
    return skf2dxf.Writer(skf2dxf.INCH_TO_M, {})


def test_symbol_names_become_distinct_valid_block_names(writer):
    writer.add_symbols({"Arbol 03": [], "Arbol_03": [], "arbol_03": [], "A/C": []})
    msp = writer.doc.modelspace()
    for name in ("Arbol 03", "Arbol_03", "arbol_03", "A/C"):
        writer.add(msp, insert(name))
    names = [e.dxf.name for e in msp.query("INSERT")]
    assert len({n.upper() for n in names}) == 4
    assert "A_C" in names
    assert writer.doc.audit().has_errors is False


def test_inserts_of_unknown_symbols_are_skipped_and_reported(writer):
    writer.add(writer.doc.modelspace(), insert("missing"))
    assert writer.report["skipped symbol"] == 1


def test_ellipse_with_long_minor_axis_keeps_its_shape(writer):
    e = entity(18, center=(0, 0), axis=(10, 0), ratio=2.0, angles=(0.3, 2.0))
    writer.add(writer.doc.modelspace(), e)
    ellipse = writer.doc.modelspace().query("ELLIPSE").first
    assert ellipse.dxf.ratio == pytest.approx(0.5)
    # AutoSketch's point at parameter t: major * cos t + (major rotated 90 degrees * ratio) * sin t
    t = 1.1
    expected = (10 * math.cos(t) * skf2dxf.INCH_TO_M, 20 * math.sin(t) * skf2dxf.INCH_TO_M)
    actual = ellipse.construction_tool().vertices([t - math.pi / 2]).__next__()
    assert actual.x == pytest.approx(expected[0]) and actual.y == pytest.approx(expected[1])


@pytest.mark.skipif(not skf2dxf.PATTERN_LIBRARY, reason="patterns.json missing")
def test_patterns_not_stored_in_the_drawing_come_from_the_library_or_autocad(writer):
    assert writer.pattern("WOODFACE")
    assert writer.pattern("ANSI31")
    assert not writer.report
    writer.pattern("NO SUCH PATTERN")
    assert writer.report["unknown hatch pattern NO SUCH PATTERN"] == 1
