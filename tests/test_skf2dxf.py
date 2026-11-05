import math

import pytest
from ezdxf import bbox, recover

import skf2dxf
from private_samples import sample

FLOOR_PLAN = sample("floor plan")
TITLE_BLOCK = sample("title block")
SECTIONS = sample("sections")
# AutoSketch's own DWG exports, converted to DXF with LibreDWG's dwg2dxf
FLOOR_PLAN_REF = sample("floor plan export")
SECTIONS_REF = sample("sections export")

needs_samples = pytest.mark.skipif(not FLOOR_PLAN.exists(), reason="private samples missing")


def test_rejects_other_files():
    with pytest.raises(skf2dxf.SkfError):
        skf2dxf.to_dxf(b"AC1032 not a sketch")


def test_rejects_truncated_drawings():
    with pytest.raises(skf2dxf.SkfError):
        skf2dxf.to_dxf(b"\x0a\x00\x00\x00\x0bEntity List\x05Layer")


@needs_samples
@pytest.mark.parametrize("path", [FLOOR_PLAN, TITLE_BLOCK, SECTIONS],
                         ids=["floor plan", "title block", "sections"])
def test_converts_samples_cleanly(path):
    doc, report = skf2dxf.to_dxf(path.read_bytes())
    warnings = {k: v for k, v in report.items() if skf2dxf.is_warning(k)}
    assert doc.audit().has_errors is False
    assert set(warnings) <= {"skipped angular dimension"}


@needs_samples
def test_matches_autosketch_export():
    doc, _ = skf2dxf.to_dxf(FLOOR_PLAN.read_bytes())
    ref, _ = recover.readfile(FLOOR_PLAN_REF)
    ext = bbox.extents(ref.modelspace().query("LINE"))

    def key(*coords):
        return tuple(round(v, 2) for v in coords)

    def inside(p):
        return ext.extmin.x - 0.5 <= p.x <= ext.extmax.x + 0.5 and \
            ext.extmin.y - 0.5 <= p.y <= ext.extmax.y + 0.5

    def lines(d):
        return {tuple(sorted([key(e.dxf.start.x, e.dxf.start.y), key(e.dxf.end.x, e.dxf.end.y)]))
                for e in d.modelspace().query("LINE") if inside(e.dxf.start)}

    def inserts(d):
        return {key(e.dxf.insert.x, e.dxf.insert.y) for e in d.modelspace().query("INSERT")
                if inside(e.dxf.insert)}

    mine_lines = lines(doc)
    assert len(mine_lines - lines(ref)) <= 2
    assert len(mine_lines) > 1300
    assert inserts(doc) <= inserts(ref)
    assert len(inserts(doc)) > 350


@needs_samples
def test_dimension_text_matches_autosketch_export():
    doc, _ = skf2dxf.to_dxf(SECTIONS.read_bytes())
    ref, _ = recover.readfile(SECTIONS_REF)
    ref_texts = [(t.dxf.text, t.dxf.align_point) for t in ref.modelspace().query("TEXT")]
    matched = 0
    for dim in doc.modelspace().query("DIMENSION"):
        text = doc.blocks.get(dim.dxf.geometry).query("MTEXT").first
        matched += any(value == text.plain_text() and at.isclose(text.dxf.insert, abs_tol=0.01)
                       for value, at in ref_texts)
    # AutoSketch moves the text of 3 tiny dimensions outside; AutoCAD keeps it centered
    assert matched >= 67


@needs_samples
def test_pattern_spacing_matches_autosketch_export():
    doc, _ = skf2dxf.to_dxf(FLOOR_PLAN.read_bytes())
    spacings = {round(math.hypot(*line.offset), 4)
                for hatch in doc.modelspace().query("HATCH") if hatch.dxf.pattern_name == "ANSI31"
                for line in hatch.pattern.lines}
    # Line spacing of the exploded ANSI31 hatches in the export
    assert spacings <= {0.0937, 0.0938}


HATCH_TEST = sample("hatch test")
# AutoSketch's export of one square per built-in pattern, at 1:100
HATCH_TEST_REF = sample("hatch test export")


def line_families(lines, box):
    """Angle -> spacing of the exploded pattern lines strictly inside a square."""
    (x0, y0), (x1, y1) = box
    families = {}
    for line in lines:
        a, b = line.dxf.start, line.dxf.end
        on_border = (abs(a.x - b.x) < 1e-6 and min(abs(a.x - x0), abs(a.x - x1)) < 1e-3) or \
            (abs(a.y - b.y) < 1e-6 and min(abs(a.y - y0), abs(a.y - y1)) < 1e-3)
        inside = all(x0 - 1e-3 <= p.x <= x1 + 1e-3 and y0 - 1e-3 <= p.y <= y1 + 1e-3 for p in (a, b))
        if inside and not on_border:
            angle = math.atan2(b.y - a.y, b.x - a.x) % math.pi
            families.setdefault(round(math.degrees(angle)) % 180, []).append(
                -a.x * math.sin(angle) + a.y * math.cos(angle))
    return {angle: round(min(b - a for a, b in zip(sorted(o), sorted(o)[1:])), 3)
            for angle, o in families.items()}


@pytest.mark.skipif(not HATCH_TEST.exists(), reason="private samples missing")
def test_builtin_patterns_match_autosketch_export():
    doc, report = skf2dxf.to_dxf(HATCH_TEST.read_bytes())
    ref, _ = recover.readfile(HATCH_TEST_REF)
    ref_lines = list(ref.modelspace().query("LINE"))
    hatches = doc.modelspace().query("HATCH")
    assert len(hatches) == 7
    assert not [k for k in report if k.startswith("unknown hatch pattern")]
    for hatch in hatches:
        box = hatch.paths[0].vertices
        corners = ((min(v[0] for v in box), min(v[1] for v in box)),
                   (max(v[0] for v in box), max(v[1] for v in box)))
        mine = {round(line.angle) % 180: round(abs(line.offset.rotate_deg(-line.angle).y), 3)
                for line in hatch.pattern.lines}
        assert mine == line_families(ref_lines, corners), hatch.dxf.pattern_name
