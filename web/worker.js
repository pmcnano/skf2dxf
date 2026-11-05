importScripts("https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.js");

const PYTHON = `
import io
import zipfile
import skf2dxf

docs = {}
outputs = {}
previews = {}

def convert(id, data):
    try:
        doc, report = skf2dxf.to_dxf(bytes(data.to_py()))
    except skf2dxf.SkfError as error:
        return {"error": "unsupported", "detail": str(error)}
    docs[id] = doc
    out = io.StringIO()
    doc.write(out)
    outputs[id] = out.getvalue()
    return {"dxf": outputs[id], "report": dict(report)}

def make_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for id, name in entries.to_py():
            archive.writestr(name, outputs[id])
    return buffer.getvalue()

def setup_fonts(folder):
    from ezdxf.fonts import fonts
    fonts.font_manager.build([folder], support_dirs=False)

def render_preview(id):
    import preview
    previews[id] = preview.Preview(docs[id])
    return {"svg": previews[id].svg, "layers": previews[id].layers()}

def make_pdf(id, hidden):
    return previews[id].pdf(set(hidden.to_py()))
`;

const HOME = "/home/pyodide";

const ready = (async () => {
  const pyodide = await loadPyodide();
  const [source, library] = await Promise.all([
    fetch("skf2dxf.py").then((r) => r.text()),
    fetch("patterns.json").then((r) => r.text()),
    pyodide.loadPackage(["micropip", "numpy", "pyparsing", "fonttools", "typing-extensions"]),
  ]);
  // Bundled with the site so loading works offline and doesn't depend on PyPI
  const wheel = new URL("vendor/ezdxf-1.4.5-py3-none-any.whl", location.href).href;
  await pyodide.pyimport("micropip").install.callKwargs(wheel, { deps: false });
  pyodide.FS.writeFile(`${HOME}/skf2dxf.py`, source);
  pyodide.FS.writeFile(`${HOME}/patterns.json`, library);
  pyodide.runPython(`import sys; sys.path.insert(0, "${HOME}")\n${PYTHON}`);
  return pyodide;
})();

// Only the preview needs Pillow (imported by ezdxf's drawing add-on) and a font to draw text
let drawingReady;

async function setupDrawing(pyodide) {
  const [source, font] = await Promise.all([
    fetch("preview.py").then((r) => r.text()),
    fetch("fonts/DejaVuSans.ttf").then((r) => r.arrayBuffer()),
    pyodide.loadPackage("pillow"),
  ]);
  pyodide.FS.writeFile(`${HOME}/preview.py`, source);
  pyodide.FS.mkdirTree(`${HOME}/fonts`);
  pyodide.FS.writeFile(`${HOME}/fonts/DejaVuSans.ttf`, new Uint8Array(font));
  pyodide.globals.get("setup_fonts")(`${HOME}/fonts`);
}

ready.then(
  () => postMessage({ type: "ready" }),
  (error) => postMessage({ type: "failed", detail: String(error) }),
);

function toJs(proxy) {
  const value = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  return value;
}

onmessage = async ({ data: { type, id, bytes, entries, hidden } }) => {
  const pyodide = await ready;
  const python = (name, ...args) => pyodide.globals.get(name)(...args);
  try {
    if (type === "convert") {
      postMessage({ id, ...toJs(python("convert", id, bytes)) });
    } else if (type === "zip") {
      const zip = toJs(python("make_zip", entries));
      postMessage({ id, zip }, [zip.buffer]);
    } else if (type === "preview") {
      drawingReady ??= setupDrawing(pyodide);
      await drawingReady;
      postMessage({ id, ...toJs(python("render_preview", id)) });
    } else if (type === "pdf") {
      const pdf = toJs(python("make_pdf", id, hidden));
      postMessage({ id, pdf }, [pdf.buffer]);
    }
  } catch (error) {
    postMessage({ id, error: "crash", detail: String(error) });
  }
};
