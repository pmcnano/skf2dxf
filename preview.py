"""Renders a converted drawing for the web page: an SVG for the viewer and a vector PDF."""
import re
import zlib

from ezdxf import colors
from ezdxf.addons.drawing import Frontend, RenderContext, config, layout, svg
from ezdxf.addons.drawing.recorder import (FilledPathsRecord, PathRecord, PointsRecord,
                                           SolidLinesRecord)
from ezdxf.path import Command

PDF_LONG_SIDE = 420 / 25.4 * 72  # A3, in points


class LayeredRenderBackend(svg.SVGRenderBackend):
    """Tags every path with a class per layer, so the viewer hides layers with CSS and the
    drawing order (fills over lines) stays as in the drawing."""

    def __init__(self, page, settings):
        super().__init__(page, settings)
        self.layer_classes = {}

    def add_strokes(self, d, properties):
        super().add_strokes(d, properties)
        self.tag(d, properties.layer)

    def add_filling(self, d, properties):
        super().add_filling(d, properties)
        self.tag(d, properties.layer)

    def tag(self, d, layer):
        if d:
            element = self.entities[-1]
            cls = self.layer_classes.setdefault(layer, f"L{len(self.layer_classes)}")
            element.set("class", f"{element.get('class')} {cls}")


class LayeredSVGBackend(svg.SVGBackend):
    def make_backend(self, page, settings):
        self.render_backend = LayeredRenderBackend(page, settings)
        return self.render_backend


class Preview:
    def __init__(self, doc):
        self.doc = doc
        self.backend = LayeredSVGBackend()
        cfg = config.Configuration(background_policy=config.BackgroundPolicy.WHITE,
                                   color_policy=config.ColorPolicy.COLOR)
        Frontend(RenderContext(doc), self.backend, config=cfg).draw_layout(doc.modelspace())
        # Also moves the recordings into SVG space: integer units, y pointing down
        image = self.backend.get_string(layout.Page(0, 0, layout.Units.mm,
                                                    layout.Margins.all(0)))
        # Hairlines at every zoom level, like a CAD viewer
        self.svg = re.sub(r"stroke-width: [\d.]+;",
                          "stroke-width: 1; vector-effect: non-scaling-stroke;", image)
        view_box = self.backend.render_backend.root.get("viewBox").split()
        self.width, self.height = int(view_box[2]), int(view_box[3])

    def layers(self):
        """Layers that have something drawn, with their color for the layer list."""
        result = []
        for name, cls in sorted(self.backend.render_backend.layer_classes.items()):
            aci = abs(self.doc.layers.get(name).color) if name in self.doc.layers else 7
            rgb = colors.aci2rgb(aci) if 0 < aci < 256 else (0, 0, 0)
            # White (ACI 7) is drawn black on paper
            result.append({"name": name, "class": cls,
                           "color": "#000000" if rgb == (255, 255, 255) else rgb.to_hex()})
        return result

    def pdf(self, hidden=()):
        k = PDF_LONG_SIDE / max(self.width, self.height)
        page_width, page_height = self.width * k, self.height * k

        def pt(v):
            return f"{v.x * k:.2f} {page_height - v.y * k:.2f}"

        def path_ops(path, close):
            if len(path) == 0:
                return []
            ops, current = [f"{pt(path.start)} m"], path.start
            for cmd in path.commands():
                if cmd.type == Command.MOVE_TO:
                    ops.append(f"{pt(cmd.end)} m")
                elif cmd.type == Command.LINE_TO:
                    ops.append(f"{pt(cmd.end)} l")
                elif cmd.type == Command.CURVE3_TO:
                    c1 = current + (cmd.ctrl - current) * (2 / 3)
                    c2 = cmd.end + (cmd.ctrl - cmd.end) * (2 / 3)
                    ops.append(f"{pt(c1)} {pt(c2)} {pt(cmd.end)} c")
                else:
                    ops.append(f"{pt(cmd.ctrl1)} {pt(cmd.ctrl2)} {pt(cmd.end)} c")
                current = cmd.end
            return ops + ["h"] if close else ops

        def polyline_ops(vertices, close):
            ops = [f"{pt(vertices[0])} m"] + [f"{pt(v)} l" for v in vertices[1:]]
            return ops + ["h"] if close else ops

        ops = ["1 J 1 j 0.3 w"]  # round caps and joins, hairline width in points
        for record, properties in self.backend.player().recordings():
            if properties.layer in hidden:
                continue
            rgb = " ".join(f"{c / 255:.3f}" for c in colors.RGB.from_hex(properties.color[:7]))
            if isinstance(record, FilledPathsRecord):
                ops.append(f"{rgb} rg")
                for path in record.paths:
                    ops += path_ops(path, close=True)
                ops.append("f*")
            elif isinstance(record, PathRecord):
                ops += [f"{rgb} RG", *path_ops(record.path, close=False), "S"]
            elif isinstance(record, SolidLinesRecord):
                vertices = record.lines.vertices()
                ops.append(f"{rgb} RG")
                for start, end in zip(vertices[::2], vertices[1::2]):
                    ops += [f"{pt(start)} m", f"{pt(end)} l"]
                ops.append("S")
            elif isinstance(record, PointsRecord):
                vertices = record.points.vertices()
                if len(vertices) > 2:
                    ops += [f"{rgb} rg", *polyline_ops(vertices, close=True), "f*"]
                elif vertices:
                    ops += [f"{rgb} RG", *polyline_ops(vertices * (3 - len(vertices)), False), "S"]
        return write_pdf(page_width, page_height, zlib.compress("\n".join(ops).encode()))


def write_pdf(width, height, content):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
        f"/Contents 4 0 R /Resources << >> >>".encode(),
        f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode() + content
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
