"""AutoSketch 10 (.skf) -> DXF converter, reverse-engineered from sample files."""
import json
import math
import re
import struct
import sys
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf.math import Vec2
from ezdxf.tools.pattern import IMPERIAL_PATTERN

INCH_TO_M = 0.0254


class SkfError(Exception):
    pass


class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def u8(self):
        self.p += 1
        return self.d[self.p - 1]

    def u16(self):
        self.p += 2
        return struct.unpack_from("<H", self.d, self.p - 2)[0]

    def u32(self):
        self.p += 4
        return struct.unpack_from("<I", self.d, self.p - 4)[0]

    def i32(self):
        self.p += 4
        return struct.unpack_from("<i", self.d, self.p - 4)[0]

    def f64(self, n=None):
        if n is None:
            self.p += 8
            return struct.unpack_from("<d", self.d, self.p - 8)[0]
        self.p += 8 * n
        return struct.unpack_from(f"<{n}d", self.d, self.p - 8 * n)

    def pstr(self):
        # MFC CString: u8 length, escaped to u16 then u32 for long strings
        n = self.u8()
        if n == 0xff:
            n = self.u16()
            if n == 0xffff:
                n = self.u32()
        self.p += n
        return self.d[self.p - n:self.p].decode("latin-1")


def read_fill(r):
    kind = r.i32()
    if kind == 1:
        r.pstr()
        rgb = tuple(r.d[r.p:r.p + 3])
        r.p += 4
        return {"kind": "solid", "rgb": rgb}
    if kind == 2:
        name = r.pstr()
        scale, angle = r.f64(2)
        r.p += 28
        return {"kind": "pattern", "name": name, "scale": scale, "angle": angle}
    return None


def parse_entity(r):
    etype, size = r.u32(), r.u32()
    end = r.p + size
    flags = r.u32()
    e = {"type": etype, "flags": flags, "layer": r.pstr()}
    # A missing field means an explicit default (black, Continuous), -1 ByLayer, -2 ByBlock
    e["color"] = r.i32() if flags & 0x02 else None
    # Colors past the 16 base ones also store their name and RGB ("RGB(255,64,0)", "Melon")
    if e["color"] is not None and e["color"] >= 16:
        r.pstr()
        e["rgb"] = tuple(r.d[r.p:r.p + 3])
        r.p += 4
    if flags & 0x04:
        e["width"] = r.i32()
    e["linetype"] = "Continuous"
    if flags & 0x08:
        index = r.i32()
        e["linetype"] = {-1: None, -2: "BYBLOCK"}.get(index)
        if 0 <= index < len(LINETYPES):
            e["linetype"] = LINETYPES[index]
        elif index >= 0:
            e["linetype"] = r.pstr()  # only custom linetypes (from the Style section) carry a name
    if flags & 0x10:
        e["f10"] = r.f64()  # unknown; 15.0 on text in AutoSketch 7-9 drawings
    if flags & 0x20:
        e["f20"] = r.u32()  # unknown; 0x8000 on text
    if flags & 0x40:
        e["f40"] = r.i32()
    if flags & 0x80:
        e["fill"] = read_fill(r)
    if flags & 0x2000:
        e["ends"] = r.d[r.p:r.p + 17]
        r.p += 17
    e["id"] = r.u32()
    PARSERS.get(etype, lambda r, e: None)(r, e)
    e["left"] = end - r.p
    r.p = end
    return e


def parse_line(r, e):
    e["pts"] = [r.f64(2), r.f64(2)]


def parse_arc(r, e):
    e["center"], e["radius"] = r.f64(2), r.f64()
    e["angles"] = r.f64(2)


def parse_circle(r, e):
    e["center"], e["radius"] = r.f64(2), r.f64()


def parse_poly(r, e):
    e["poly_flags"], e["poly_b"], n = r.u32(), r.u32(), r.u32()
    r.p += 16
    e["pts"] = [r.f64(2) for _ in range(n)]
    e["bulges"], e["vflags"] = [0.0] * n, [0] * n
    if e["poly_flags"] & 0x20:
        for i in range(n):
            e["bulges"][i] = r.f64(3)[2]
            e["vflags"][i] = r.u32()
            r.p += 4


def parse_arrow(r, e):
    e["insert"], e["scale"] = r.f64(2), r.f64(2)
    r.f64()
    e["rotation"] = r.f64()


def parse_ellipse18(r, e):
    e["center"], e["ratio"], e["axis"] = r.f64(2), r.f64(), r.f64(2)
    r.f64()
    e["angles"] = r.f64(2)


def parse_text(r, e):
    e["insert"] = r.f64(2)
    e["rotation"], e["width_factor"] = r.f64(2)
    e["runs"] = []
    for _ in range(r.u32()):
        text, height = r.pstr(), r.f64()
        r.f64()
        font, color, flags = r.pstr(), r.i32(), r.u32()
        e["runs"].append({"text": text, "height": height, "font": font, "color": color,
                          "flags": flags})
    e["align"], e["tail"] = r.u32(), (r.u32(), r.u32(), r.f64())


def parse_insert(r, e):
    e["insert"], e["scale"] = r.f64(2), r.f64(2)
    r.f64()
    e["rotation"], e["name"] = r.f64(), r.pstr()


def parse_dimension(r, e):
    """Linear dimension; AutoSketch's DWG export explodes these into lines, text and arrows."""
    e["arrow"], e["height"] = r.f64(2)
    r.p += 18
    e["font"], e["text_color"], e["decimals"] = r.pstr(), r.i32(), r.i32()
    r.p += 24
    e["ext_offset"], e["ext_beyond"] = r.f64(2)
    r.p += 16
    e["dim_flags"], e["text"] = r.u32(), r.pstr()
    e["p1"], e["p2"], e["line_at"], e["text_at"] = (r.f64(2) for _ in range(4))
    e["angle"] = r.f64()


def parse_group(r, e):
    e["children"] = [parse_entity(r) for _ in range(r.u32())]


PARSERS = {1: parse_line, 2: parse_arc, 3: parse_circle, 4: parse_poly, 6: parse_poly,
           8: parse_arrow, 9: parse_text, 10: parse_dimension, 14: parse_insert, 18: parse_ellipse18,
           19: parse_group}


def parse_layers(data):
    # Sections are a u32 body size followed by the section name
    start = data.find(b"\x05Layer")
    r = Reader(data, start + 6)
    end = r.p + struct.unpack_from("<I", data, start - 4)[0]
    layers = []
    while r.p < end - 1:
        name, _alias = r.pstr(), r.pstr()
        flags, color, width, linetype = r.u32(), r.u32(), r.u32(), r.u32()
        layers.append({"name": name, "flags": flags, "color": color, "width": width,
                       "linetype": linetype})
    return layers


def parse_hatch_styles(data):
    """Pattern definitions embedded in the drawing, in inches, keyed by upper-case name."""
    start = data.find(b"\x0bHatch Style")
    if start < 0:
        return {}
    r = Reader(data, start + 12)
    end = r.p + struct.unpack_from("<I", data, start - 4)[0]
    patterns = {}
    while r.p < end - 1:
        name, _name, _description, _file = r.pstr(), r.pstr(), r.pstr(), r.pstr()
        unit = 1 / 25.4 if r.u32() == 1 else 1  # 1: metric .pat file such as AcadISO.pat
        lines = []
        for _ in range(r.u32()):
            r.u16()
            ox, oy, dx, dy, _period = r.f64(5)
            dashes = [v * unit for v in r.f64(r.u32())]
            lines.append((r.f64(), (ox * unit, oy * unit), (dx * unit, dy * unit), dashes))
        patterns[name.upper()] = lines
    return patterns


def parse_drawing_scale(data):
    """Paper/drawing ratio from Drawing Variables entry 142, e.g. 0.01 at 1:100."""
    start = data.find(b"\x11Drawing Variables")
    entry = data.find(b"\x8e\x00\x00\x00\x03\x01\x01\x00", start, data.find(b"\x05Layer", start))
    if start < 0 or entry < 0:
        return 0.01
    return struct.unpack_from("<d", data, entry + 8)[0] or 0.01


def parse(data):
    if not data.startswith(b"\x0a\x00\x00\x00") or b"\x0bEntity List" not in data:
        raise SkfError("not an AutoSketch drawing, or a version this converter can't read yet")
    symbols = {}
    start = data.find(b"\x12Symbol Definitions")
    r = Reader(data, start + 19)
    # Drawings without symbols have no Symbol Definitions section at all
    while start >= 0 and data[r.p] and data[r.p:r.p + 14] != b"\x0dColor Palette":
        name = r.pstr()
        size = r.u32()
        end = r.p + size
        flags = r.u32()
        r.pstr()
        # 0x100: data fields attached to the symbol, e.g. EstimateID = 99.81500
        attributes = r.u32() if flags & 0x100 else 0
        r.u32()
        for _ in range(attributes):
            r.pstr()
            r.p += 15
            r.pstr()
        symbols[name] = [parse_entity(r) for _ in range(r.u32())]
        r.p = end
    r = Reader(data, data.find(b"\x0bEntity List") + 12)
    r.pstr()
    r.u32()
    return symbols, [parse_entity(r) for _ in range(r.u32())]


LINETYPES = ["Continuous", "HIDDEN", "DASHED", "CENTER", "PHANTOM", "DOT", "DASHDOT", "DIVIDE",
             "BORDER"]
# acad.lin definitions missing from ezdxf's standard set
EXTRA_LINETYPES = {"HIDDEN": [0.375, 0.25, -0.125], "HIDDEN2": [0.1875, 0.125, -0.0625],
                   "HIDDENX2": [0.75, 0.5, -0.25],
                   "BORDER": [1.75, 0.5, -0.25, 0.5, -0.25, 0.0, -0.25]}
# AutoSketch base colors; 0, 1, 2, 4, 5, 12 and 15 are confirmed against AutoSketch's own DWG export.
BASE_ACI = {0: 7, 1: 1, 2: 5, 3: 2, 4: 3, 5: 4, 6: 6, 7: 7, 8: 7, 12: 94, 15: 8}
TEXT_ALIGN = ["LEFT", "CENTER", "RIGHT", "MIDDLE_LEFT", "MIDDLE_CENTER", "MIDDLE_RIGHT",
              "TOP_LEFT", "TOP_CENTER", "TOP_RIGHT"]
MTEXT_ATTACH = [7, 8, 9, 4, 5, 6, 1, 2, 3]
# AutoSketch's built-in patterns aren't stored in the drawing. Measured from AutoSketch's DWG
# export, which draws them as solid lines 0.25" apart on paper, sized by the drawing scale.
D = math.radians
BUILTIN_PATTERNS = {
    "IRON": [(D(45), (0, 0), (0, 0.25), [])],
    "SQUARE GRID": [(0, (0, 0), (0, 0.25), []), (D(90), (0, 0), (0, 0.25), [])],
    "INSULATION": [(D(45), (0, 0), (0, 0.25), []), (D(135), (0, 0), (0, 0.25), [])],
    "DIAMOND": [(D(60), (0, 0), (0, 0.25), []), (D(120), (0, 0), (0, 0.25), [])],
    "TRIANGLE": [(0, (0, 0), (0, 0.25), []), (D(60), (0, 0), (0, 0.25), []),
                 (D(120), (-0.108253, -0.0625), (0, 0.25), [])],
    "DOTTED": [(0, (0, 0), (0, 0.25), [])],
    "DASHED": [(D(45), (0, 0), (0, 0.25), [])],
}
# Patterns stored in other drawings of the office archive (tools/build_pattern_library.py), for
# drawings that use one without storing it
LIBRARY_PATH = Path(__file__).with_name("patterns.json")
PATTERN_LIBRARY = json.loads(LIBRARY_PATH.read_text()) if LIBRARY_PATH.exists() else {}
# Decimals for dimensions set to the drawing default; where the default lives is still unknown
DEFAULT_DECIMALS = 4
ENTITY_NAMES = {1: "line", 2: "arc", 3: "circle", 4: "polyline", 6: "polygon", 8: "arrowhead",
                9: "text", 10: "dimension", 11: "angular dimension", 14: "symbol", 18: "ellipse", 19: "group"}


def aci(index, report):
    if index < 16:
        if index not in BASE_ACI:
            report[f"unknown color index {index}"] += 1
        return BASE_ACI.get(index, 7)
    return index - 6


def block_name(name):
    # Spaces like AutoSketch's own export; the rest aren't allowed in DXF names
    return re.sub(r'[\s<>/\\":;?*|=`]', "_", name)


class Writer:
    def __init__(self, scale, patterns, drawing_scale=0.01):
        self.s = scale
        self.patterns = patterns
        self.drawing_scale = drawing_scale
        self.blocks = {}  # symbol name -> DXF block name
        self.report = Counter()
        self.doc = ezdxf.new("R2010", setup=True)
        self.doc.units = ezdxf.units.M
        self.doc.header["$MEASUREMENT"] = 1
        self.doc.header["$LTSCALE"] = scale
        self.doc.styles.add("Arial", font="arial.ttf")
        for name, pattern in EXTRA_LINETYPES.items():
            if name not in self.doc.linetypes:
                self.doc.linetypes.add(name, pattern=pattern)
        # Horizontal text centered in a gap of the dimension line, trailing zeros kept
        self.doc.dimstyles.new("AUTOSKETCH", dxfattribs={
            "dimtxsty": "Arial", "dimtih": 1, "dimtoh": 1, "dimtad": 0, "dimtix": 1, "dimzin": 0,
            "dimdsep": ord("."), "dimclrd": 0, "dimclre": 0, "dimclrt": 0})

    def pt(self, p):
        return (p[0] * self.s, p[1] * self.s)

    def attribs(self, e, layer):
        a = {"layer": layer}
        if e["color"] is None:
            a["color"] = 7
        elif e["color"] == -2:
            a["color"] = 0
        elif e["color"] != -1:
            a["color"] = aci(e["color"], self.report)
        if "rgb" in e:
            a["true_color"] = ezdxf.colors.rgb2int(e["rgb"])
        if e.get("linetype"):
            if e["linetype"] in self.doc.linetypes or e["linetype"] == "BYBLOCK":
                a["linetype"] = e["linetype"]
            else:
                self.report[f"unknown linetype {e['linetype']}"] += 1
        return a

    def add_layers(self, layers):
        for l in layers:
            if l["name"] in self.doc.layers:
                layer = self.doc.layers.get(l["name"])
            else:
                layer = self.doc.layers.add(l["name"])
            layer.color = aci(l["color"], self.report)
            if l["linetype"] < len(LINETYPES):
                layer.dxf.linetype = LINETYPES[l["linetype"]]

    def add_symbols(self, symbols):
        for name in symbols:
            # "Arbol 03" and "Arbol_03" (or "arbol_03": DXF ignores case) would collide
            base = candidate = block_name(name)
            while candidate in self.doc.blocks:
                candidate = f"{base}_{len(self.blocks) + 1}"
            self.blocks[name] = self.doc.blocks.new(candidate).name
        for name, ents in symbols.items():
            block = self.doc.blocks.get(self.blocks[name])
            for e in ents:
                self.add(block, e, in_block=True)
        if "ARROW" not in self.doc.blocks:
            block = self.doc.blocks.new("ARROW")
            tri = [(0, 0), (0.5 * self.s, 0.5 * self.s), (0.5 * self.s, -0.5 * self.s)]
            block.add_lwpolyline(tri, close=True)
            block.add_hatch().paths.add_polyline_path(tri)

    def add(self, space, e, in_block=False):
        layer = "0" if in_block else e["layer"]
        if layer not in self.doc.layers:
            self.doc.layers.add(layer)
        t, a = e["type"], self.attribs(e, layer)
        if t == 1:
            space.add_line(*map(self.pt, e["pts"]), dxfattribs=a)
        elif t == 2:
            space.add_arc(self.pt(e["center"]), e["radius"] * self.s,
                          *(math.degrees(v) for v in e["angles"]), dxfattribs=a)
        elif t == 3:
            space.add_circle(self.pt(e["center"]), e["radius"] * self.s, dxfattribs=a)
        elif t in (4, 6):
            self.add_poly(space, e, a)
        elif t == 8:
            space.add_blockref("ARROW", self.pt(e["insert"]), dxfattribs={
                **a, "xscale": e["scale"][0], "yscale": e["scale"][1],
                "rotation": math.degrees(e["rotation"])})
        elif t == 9:
            self.add_text(space, e, a)
        elif t == 10:
            self.add_dimension(space, e, a)
        elif t == 14:
            if e["name"] not in self.blocks:
                self.report["skipped symbol"] += 1
                return
            space.add_blockref(self.blocks[e["name"]], self.pt(e["insert"]), dxfattribs={
                **a, "xscale": e["scale"][0], "yscale": e["scale"][1],
                "rotation": math.degrees(e["rotation"])})
        elif t == 18:
            self.add_ellipse(space, e, a)
        elif t == 19:
            for child in e["children"]:
                self.add(space, child, in_block)
        else:
            self.report[f"skipped {ENTITY_NAMES.get(t, f'entity type {t}')}"] += 1
            return
        if t != 19 and not in_block:
            self.report[ENTITY_NAMES[t]] += 1

    def add_poly(self, space, e, a):
        loops = self.poly_loops(e)
        fill = e.get("fill")
        if fill:
            hatch = space.add_hatch(dxfattribs={"layer": a["layer"]})
            if fill["kind"] == "solid":
                hatch.set_solid_fill(color=self.fill_color(fill["rgb"]))
            else:
                name = fill["name"].upper()
                hatch.set_pattern_fill(name, definition=self.pattern(name),
                                       scale=fill["scale"] * self.s,
                                       angle=math.degrees(fill["angle"]))
            for verts, _closed in loops:
                hatch.paths.add_polyline_path(verts, is_closed=True)
        # Color 8 on a filled shape: AutoSketch's export drops the outline
        if not (fill and e["color"] == 8):
            for verts, closed in loops:
                space.add_lwpolyline(verts, format="xyb", close=closed, dxfattribs=a)

    def pattern(self, name):
        if name in self.patterns:
            lines, factor = self.patterns[name], 1
        elif name in BUILTIN_PATTERNS:
            # Built-ins are in paper inches: 0.25" is 25" of drawing at 1:100
            lines, factor = BUILTIN_PATTERNS[name], 1 / self.drawing_scale
        elif name in PATTERN_LIBRARY:
            lines, factor = PATTERN_LIBRARY[name], 1
        elif name in IMPERIAL_PATTERN:
            return IMPERIAL_PATTERN[name]
        else:
            self.report[f"unknown hatch pattern {name}"] += 1
            return IMPERIAL_PATTERN["ANSI31"]
        # DXF stores each line's offset rotated by the line angle
        return [[math.degrees(angle), Vec2(base) * factor, Vec2(offset).rotate(angle) * factor,
                 [d * factor for d in dashes]]
                for angle, base, offset, dashes in lines]

    def poly_loops(self, e):
        """Split at vertices flagged 0x04, which start a new loop (e.g. a hole)."""
        loops, current = [], []
        for p, bulge, vflag in zip(e["pts"], e["bulges"], e["vflags"]):
            if vflag & 0x04 and current:
                loops.append(current)
                current = []
            current.append((*self.pt(p), bulge))
        loops.append(current)
        result = []
        for verts in loops:
            closed = e["type"] == 6 or len(loops) > 1
            if len(verts) > 2 and verts[0][:2] == verts[-1][:2]:
                verts, closed = verts[:-1], True
            result.append((verts, closed))
        return result

    @staticmethod
    def fill_color(rgb):
        for i in range(1, 256):
            if ezdxf.colors.aci2rgb(i) == rgb:
                return i
        return 7

    def add_ellipse(self, space, e, a):
        axis, ratio, start, end = Vec2(e["axis"]), e["ratio"], *e["angles"]
        # AutoSketch allows the "major" axis to be the shorter one; DXF needs ratio <= 1
        if ratio > 1:
            axis, ratio = axis.orthogonal() * ratio, 1 / ratio
            start, end = start - math.pi / 2, end - math.pi / 2
        space.add_ellipse(self.pt(e["center"]), major_axis=self.pt(axis), ratio=ratio,
                          start_param=start, end_param=end, dxfattribs=a)

    def add_dimension(self, space, e, a):
        dim = space.add_linear_dim(
            base=self.pt(e["line_at"]), p1=self.pt(e["p1"]), p2=self.pt(e["p2"]),
            angle=math.degrees(e["angle"]), text=e["text"], dimstyle="AUTOSKETCH",
            override={
                "dimasz": e["arrow"] * self.s, "dimtxt": e["height"] * self.s,
                "dimexo": e["ext_offset"] * self.s, "dimexe": e["ext_beyond"] * self.s,
                "dimgap": e["height"] * self.s / 4,
                "dimdec": e["decimals"] if e["decimals"] >= 0 else DEFAULT_DECIMALS},
            dxfattribs=a)
        # text_at equals line_at unless the text was dragged away from the dimension line
        if e["text_at"] != e["line_at"]:
            dim.set_location(self.pt(e["text_at"]), leader=False)
        dim.render()

    def add_text(self, space, e, a):
        runs = e["runs"]
        rot = math.degrees(e["rotation"])
        pos = self.pt(e["insert"])
        align = e["align"] if e["align"] < 9 else 0
        if len(runs) == 1:
            text = space.add_text(runs[0]["text"], height=runs[0]["height"] * self.s,
                                  rotation=rot, dxfattribs={**a, "style": "Arial"})
            text.set_placement(pos, align=ezdxf.enums.TextEntityAlignment[TEXT_ALIGN[align]])
            return
        height = runs[0]["height"] * self.s
        parts = []
        for run in runs:
            chunk = run["text"].replace("\\", "\\\\")
            if run["flags"] & 0x04:
                chunk = f"\\L{chunk}\\l"
            if run["flags"] & 0x01:
                chunk = f"{{\\fArial|b1;{chunk}}}"
            if run["color"] == 0:
                chunk = f"{{\\C7;{chunk}}}"
            if abs(run["height"] * self.s - height) > 1e-9:
                chunk = f"{{\\H{run['height'] * self.s:.4g};{chunk}}}"
            parts.append(chunk + ("\\P" if run["flags"] & 0x80 else ""))
        space.add_mtext("".join(parts), dxfattribs={
            **a, "style": "Arial", "char_height": height, "insert": pos, "rotation": rot,
            "attachment_point": MTEXT_ATTACH[align], "line_spacing_factor": 0.9})


def to_dxf(data, scale=INCH_TO_M):
    """Returns the ezdxf document and a Counter of converted, skipped and unknown items."""
    try:
        symbols, entities = parse(data)
        layers = parse_layers(data)
        patterns = parse_hatch_styles(data)
        drawing_scale = parse_drawing_scale(data)
    except (struct.error, IndexError, ValueError) as error:
        raise SkfError("the drawing contains data this converter can't read yet") from error
    w = Writer(scale, patterns, drawing_scale)
    w.add_layers(layers)
    w.add_symbols(symbols)
    msp = w.doc.modelspace()
    for e in entities:
        w.add(msp, e)
    return w.doc, w.report


def is_warning(key):
    return key.startswith(("skipped", "unknown"))


def convert(src, dst, scale=INCH_TO_M):
    with open(src, "rb") as f:
        doc, report = to_dxf(f.read(), scale)
    doc.saveas(dst)
    return report


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: skf2dxf drawing.skf drawing.dxf")
    try:
        report = convert(sys.argv[1], sys.argv[2])
    except SkfError as error:
        sys.exit(f"{sys.argv[1]}: {error}")
    for k, v in sorted(report.items(), key=lambda kv: (is_warning(kv[0]), kv[0])):
        print(f"{v:6}  {k}")


if __name__ == "__main__":
    main()
