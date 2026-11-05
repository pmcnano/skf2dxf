import re

import pytest

import preview
import skf2dxf
from private_samples import sample

SECTIONS = sample("sections")

pytestmark = pytest.mark.skipif(not SECTIONS.exists(), reason="private samples missing")


@pytest.fixture(scope="module")
def drawing():
    doc, _ = skf2dxf.to_dxf(SECTIONS.read_bytes())
    return preview.Preview(doc)


def test_tags_every_path_with_its_layer(drawing):
    classes = {layer["class"] for layer in drawing.layers()}
    path_classes = re.findall(r'<path d="[^"]*" class="C\w+ (L\d+)"', drawing.svg)
    assert "01COTAS" in {layer["name"] for layer in drawing.layers()}
    assert set(path_classes) == classes
    assert drawing.svg.count("<path") == len(path_classes)


def test_pdf_cross_reference_points_at_each_object(drawing):
    pdf = drawing.pdf()
    xref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
    offsets = [int(o) for o in re.findall(rb"(\d{10}) 00000 n", pdf[xref:])]
    assert pdf.startswith(b"%PDF-1.4")
    assert [pdf[o:].split(b"\n")[0] for o in offsets] == [b"1 0 obj", b"2 0 obj", b"3 0 obj",
                                                          b"4 0 obj"]


def test_pdf_leaves_out_hidden_layers(drawing):
    everything = drawing.pdf()
    without_dimensions = drawing.pdf(hidden={"01COTAS"})
    nothing = drawing.pdf(hidden={layer["name"] for layer in drawing.layers()})
    assert len(nothing) < len(without_dimensions) < len(everything)
