const t = {
  loadFailed: "The converter couldn't load. Check your connection and reload the page.",
  waiting: "Waiting for the converter…",
  converting: "Converting…",
  addMore: "Add more .skf files",
  progress: (done, total) => `Converting… ${done} of ${total} done.`,
  summary: (ok, total) => {
    if (ok === total) return total === 1 ? "1 file converted." : `All ${total} files converted.`;
    if (total === 1) return "The file couldn't be converted.";
    return `${ok} of ${total} files converted · ${total - ok} couldn't be converted.`;
  },
  download: "Download DXF",
  downloadAll: (n) => `Download all ${n} DXF (.zip)`,
  zipping: "Preparing the .zip…",
  preview: "Preview",
  hidePreview: "Hide preview",
  previewing: "Drawing the preview…",
  previewFailed: "The preview couldn't be drawn.",
  zoomIn: "Zoom in",
  zoomOut: "Zoom out",
  zoomFit: "Fit",
  fullScreen: "Full screen",
  exitFullScreen: "Exit full screen",
  layers: "Layers",
  showAll: "Show all",
  hideAll: "Hide all",
  closeLayers: "Done",
  pdf: "Download PDF",
  pdfTitle: "Download a PDF of the drawing (without hidden layers)",
  pdfFailed: "Couldn't create the PDF. Try again.",
  previewLabel: (name) => `Preview of ${name}`,
  hintIdle: matchMedia("(pointer: coarse)").matches ? "Tap to zoom and move"
    : "Click to zoom with the scroll wheel and drag to move",
  hintActive: matchMedia("(pointer: coarse)").matches ? "Pinch to zoom · drag to move"
    : "Scroll to zoom · drag to move · Esc when done",
  converted: (n, output) => `${n.toLocaleString("en")} items converted → ${output}`,
  downloadNamed: (output) => `Download ${output}`,
  state: { pending: "", ok: "Converted: ", warn: "Converted with warnings: ", error: "Not converted: " },
  dwg: "This is already a DWG file. AutoCAD opens it directly; this tool is only for AutoSketch .skf drawings.",
  dxf: "This is already a DXF file. AutoCAD opens it directly; this tool is only for AutoSketch .skf drawings.",
  skippedAngular: (n) => `${n} angular dimension${n === 1 ? "" : "s"} not converted.`,
  skipped: (n, what) => `${n} item${n === 1 ? "" : "s"} not converted (${what}).`,
  unknownColor: "Some colors weren't recognized and were set to black.",
  unknownLinetype: (name) => `Unknown linetype ${name}; drawn continuous.`,
  unknownPattern: (name) => `Unknown hatch pattern ${name}; drawn as diagonal lines.`,
  unsupported: "We couldn't read this drawing. It may be from an AutoSketch version we haven't seen yet. Send it to us and we'll look at it.",
  crash: "Something went wrong converting this drawing. Send it to us and we'll look at it.",
  reportProblem: "Send us this file so we can fix it",
  reportLooksWrong: "Does something look wrong? Send us this file",
  reportTitle: (name) => `Send ${name} to us`,
  reportNote: "The file will be uploaded to our server only to improve the converter. We don't share it with anyone.",
  reportComment: "What looks wrong? (optional)",
  reportContact: "Your email, if you'd like a reply (optional)",
  reportSend: "Send this drawing",
  reportCancel: "Cancel",
  reportSending: "Sending…",
  reportThanks: "Thanks, we got it.",
  reportFailed: "It couldn't be sent. Check your connection and try again.",
  reportBusy: "That's a lot of files in a row. Wait a minute and try again.",
};

const drop = document.getElementById("drop");
const input = document.getElementById("files");
const choose = document.getElementById("choose");
const loading = document.getElementById("loading");
const summary = document.getElementById("summary");
const status = document.getElementById("status");
const zipButton = document.getElementById("zip");
const zipError = document.getElementById("zip-error");
const results = document.getElementById("results");
const tip = document.getElementById("tip");
// Converted files available for the ZIP, in the order they were chosen
const converted = [];
let ready = false;
let queued = 0;

const worker = new Worker("worker.js");
const pending = new Map();
let nextId = 0;

worker.onmessage = ({ data }) => {
  if (data.type === "ready") {
    ready = true;
    drop.classList.remove("loading");
    results.querySelectorAll(".detail.waiting").forEach((detail) => {
      detail.classList.remove("waiting");
      detail.textContent = t.converting;
    });
    updateSummary();
  } else if (data.type === "failed") {
    console.error(data.detail);
    drop.classList.replace("loading", "failed");
    loading.textContent = t.loadFailed;
  } else {
    pending.get(data.id)(data);
    pending.delete(data.id);
  }
};

// iOS greys out files whose extension it doesn't recognize, so it gets to pick anything
if (/iP(hone|ad|od)/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) {
  input.removeAttribute("accept");
}

choose.addEventListener("click", () => input.click());
drop.addEventListener("click", (event) => { if (!event.target.closest("button")) input.click(); });
input.addEventListener("change", () => convertAll(input.files));

// Files dropped anywhere on the page convert; otherwise the browser would open them itself.
// Conversions requested while the converter loads wait for it.
let dragDepth = 0;
window.addEventListener("dragenter", (event) => {
  if (!event.dataTransfer.types.includes("Files")) return;
  dragDepth++;
  document.body.classList.add("dragging");
});
window.addEventListener("dragleave", () => {
  if (--dragDepth > 0) return;
  dragDepth = 0;
  document.body.classList.remove("dragging");
});
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("dragging");
  if (event.dataTransfer.files.length) convertAll(event.dataTransfer.files);
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch((error) => console.error(error));
}

// Opening a .skf file with the installed app (Chrome's file handling)
if ("launchQueue" in window) {
  launchQueue.setConsumer(async ({ files }) => {
    if (files.length) convertAll(await Promise.all(files.map((handle) => handle.getFile())));
  });
}

function request(message, transfer = []) {
  return new Promise((resolve) => {
    pending.set(message.id, resolve);
    worker.postMessage(message, transfer);
  });
}

async function convertAll(files) {
  const batch = Array.from(files).map((file) => ({ file, item: addResult(file.name) }));
  input.value = "";
  queued += batch.length;
  drop.classList.add("compact");
  choose.textContent = t.addMore;
  updateSummary();
  for (const { file, item } of batch) {
    await convert(file, item);
    queued--;
    updateSummary();
  }
}

async function convert(file, item) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const version = autosketchVersion(bytes); // before the bytes move to the worker
  const id = nextId++;
  // People searching "skf to dwg" drop DWGs too; they need a different answer than "unreadable"
  const cad = file.name.match(/\.(dwg|dxf)$/i)?.[1].toLowerCase();
  const result = cad ? { error: cad } : await request({ type: "convert", id, bytes }, [bytes.buffer]);
  showResult(item, id, file, result);
  trackConversion(result, version, file.size);
}

function updateSummary() {
  const total = results.children.length;
  const failed = results.querySelectorAll("li.error").length;
  summary.hidden = total === 0;
  if (!ready) status.textContent = t.waiting;
  else if (queued) status.textContent = t.progress(total - queued, total);
  else status.textContent = t.summary(total - failed, total);
  zipButton.hidden = converted.length < 2;
  zipButton.disabled = queued > 0;
  zipButton.textContent = t.downloadAll(converted.length);
}

// Anonymous usage counts (see privacy.html); never file names or contents
function track(name, data = {}) {
  const body = new Blob([JSON.stringify({ name, lang: navigator.language, ...data })], { type: "application/json" });
  navigator.sendBeacon?.("api/event", body);
}

function trackConversion(result, version, size) {
  const warnings = result.error ? [] : Object.keys(result.report).filter(isWarning).sort();
  track("convert", {
    result: result.error ?? (warnings.length ? "warnings" : "ok"),
    version,
    sizeKb: Math.round(size / 1024),
    warnings: warnings.join(", "),
    count: result.error ? 0 : convertedCount(result.report),
  });
}

// Same reading as tools/survey.py: u32 10, two bytes, then format id and version strings
function autosketchVersion(bytes) {
  if (bytes.length < 8 || bytes[0] !== 10 || bytes[1] || bytes[2] || bytes[3]) return "unrecognized";
  let p = 6;
  const pstr = () => {
    const text = String.fromCharCode(...bytes.subarray(p + 1, p + 1 + bytes[p]));
    p += 1 + bytes[p];
    return text;
  };
  return `${pstr()} v${pstr()}`;
}

const ICONS = {
  pending: '<circle cx="8" cy="8" r="5.5"/>',
  ok: '<path d="M3 8.5l3.2 3.2L13 4.8"/>',
  warn: '<path d="M8 2.2l6.3 11.3H1.7z"/><path d="M8 6.5v3.3M8 11.6v.4"/>',
  error: '<circle cx="8" cy="8" r="6"/><path d="M5.6 5.6l4.8 4.8M10.4 5.6l-4.8 4.8"/>',
};

function addResult(name) {
  const item = document.createElement("li");
  item.innerHTML = `<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"></svg>
    <span class="name"><span class="visually-hidden"></span><span></span></span>
    <span class="detail"></span>`;
  item.querySelector(".name span:last-child").textContent = name;
  const detail = item.querySelector(".detail");
  detail.textContent = ready ? t.converting : t.waiting;
  detail.classList.toggle("waiting", !ready);
  setState(item, "pending");
  results.append(item);
  return item;
}

function setState(item, state) {
  item.className = state;
  item.querySelector(".icon").innerHTML = ICONS[state];
  item.querySelector(".visually-hidden").textContent = t.state[state];
}

function showResult(item, id, file, result) {
  const name = file.name;
  const detail = item.querySelector(".detail");
  if (result.error) {
    if (result.detail) console.error(name, result.detail);
    setState(item, "error");
    detail.textContent = t[result.error];
    item.append(reportForm(file, result));
    return;
  }
  const output = name.replace(/\.skf$/i, "") + ".dxf";
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([result.dxf], { type: "application/dxf" }));
  link.download = output;
  link.textContent = t.download;
  link.ariaLabel = t.downloadNamed(output);
  item.insertBefore(link, detail);
  detail.textContent = t.converted(convertedCount(result.report), output);

  const warnings = describeWarnings(result.report);
  setState(item, warnings.length ? "warn" : "ok");
  if (warnings.length) {
    const list = document.createElement("ul");
    list.className = "warnings";
    list.append(...warnings.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
    detail.after(list);
  }
  item.append(previewToggle(item, id, output), reportForm(file, result));
  converted.push({ id, name: output });
  tip.hidden = false;
}

// Report keys come from skf2dxf.py: "skipped <entity>", "unknown color index N",
// "unknown linetype X", "unknown hatch pattern X"
function isWarning(key) {
  return key.startsWith("skipped") || key.startsWith("unknown");
}

function convertedCount(report) {
  return Object.entries(report).filter(([key]) => !isWarning(key)).reduce((sum, [, n]) => sum + n, 0);
}

function describeWarnings(report) {
  const warnings = new Set();
  for (const [key, n] of Object.entries(report)) {
    if (key === "skipped angular dimension") warnings.add(t.skippedAngular(n));
    else if (key.startsWith("skipped ")) warnings.add(t.skipped(n, key.slice(8)));
    else if (key.startsWith("unknown color")) warnings.add(t.unknownColor);
    else if (key.startsWith("unknown linetype ")) warnings.add(t.unknownLinetype(key.slice(17)));
    else if (key.startsWith("unknown hatch pattern ")) warnings.add(t.unknownPattern(key.slice(22)));
  }
  return [...warnings];
}

zipButton.addEventListener("click", async () => {
  zipButton.disabled = true;
  zipButton.textContent = t.zipping;
  zipError.hidden = true;
  const result = await request({ type: "zip", id: nextId++, entries: uniqueNames(converted) });
  updateSummary();
  if (result.error) {
    console.error(result.detail);
    zipError.hidden = false;
    return;
  }
  save(new Blob([result.zip], { type: "application/zip" }), `skf2dxf-${new Date().toISOString().slice(0, 10)}.zip`);
  track("zip", { count: converted.length });
});

// Two drawings with the same name would overwrite each other inside the ZIP
function uniqueNames(files) {
  const seen = new Map();
  return files.map(({ id, name }) => {
    const n = seen.get(name) ?? 0;
    seen.set(name, n + 1);
    return [id, n ? name.replace(/\.dxf$/, ` (${n + 1}).dxf`) : name];
  });
}

function save(blob, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
}

function previewToggle(item, id, name) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "preview-toggle";
  button.textContent = t.preview;
  button.ariaExpanded = "false";
  let panel;
  button.addEventListener("click", async () => {
    if (panel) {
      panel.hidden = !panel.hidden;
      button.textContent = panel.hidden ? t.preview : t.hidePreview;
      button.ariaExpanded = String(!panel.hidden);
      return;
    }
    panel = document.createElement("div");
    panel.className = "preview";
    panel.textContent = t.previewing;
    button.after(panel);
    button.textContent = t.hidePreview;
    button.ariaExpanded = "true";
    // Each preview reuses the id of its conversion, so it gets its own reply slot
    const result = await request({ type: "preview", id });
    if (result.error) {
      console.error(result.detail);
      panel.textContent = t.previewFailed;
      return;
    }
    showPreview(panel, id, name, result);
    track("preview");
  });
  return button;
}

function showPreview(panel, id, name, { svg: markup, layers }) {
  const svg = document.importNode(
    new DOMParser().parseFromString(markup, "image/svg+xml").documentElement, true);
  svg.removeAttribute("width");
  svg.removeAttribute("height");
  // Every path carries its layer's class, so hiding a layer is one CSS rule
  const hiddenStyle = document.createElementNS("http://www.w3.org/2000/svg", "style");
  svg.append(hiddenStyle);
  const hidden = new Set();
  const updateHidden = () => {
    hiddenStyle.textContent = [...hidden].map((layer) => `.${layer.class}{display:none}`).join("");
  };

  const layerList = document.createElement("div");
  layerList.className = "preview-layers";
  layerList.hidden = true;
  const all = button(t.hideAll, null, () => {
    const hide = hidden.size < layers.length;
    layers.forEach((layer) => (hide ? hidden.add(layer) : hidden.delete(layer)));
    layerList.querySelectorAll("input").forEach((box) => { box.checked = !hide; });
    all.textContent = hide ? t.showAll : t.hideAll;
    updateHidden();
  });
  layerList.append(all);
  for (const layer of layers) {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    box.addEventListener("change", () => {
      box.checked ? hidden.delete(layer) : hidden.add(layer);
      updateHidden();
    });
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = layer.color;
    const text = document.createElement("span");
    text.textContent = layer.name;
    label.append(box, swatch, text);
    layerList.append(label);
  }

  const done = button(t.closeLayers, null, () => toggleLayers(false));
  done.className = "preview-layers-done";
  layerList.prepend(done);

  svg.setAttribute("role", "img");
  svg.ariaLabel = t.previewLabel(name);
  const hint = Object.assign(document.createElement("p"), { className: "preview-hint" });
  const canvas = document.createElement("div");
  canvas.className = "preview-canvas";
  canvas.append(svg, layerList, hint);
  const error = Object.assign(document.createElement("p"), {
    className: "preview-error", textContent: t.pdfFailed, hidden: true });
  const controls = document.createElement("div");
  controls.className = "preview-controls";
  panel.replaceChildren(controls, canvas, error);

  // The drawing only takes the wheel and touch gestures once someone clicks into it, so the
  // page still scrolls past it
  const isActive = () => canvas.classList.contains("active") || document.fullscreenElement === panel;
  const setActive = (active) => {
    canvas.classList.toggle("active", active);
    hint.textContent = isActive() ? t.hintActive : t.hintIdle;
  };
  setActive(false);
  canvas.addEventListener("pointerdown", () => setActive(true));
  document.addEventListener("pointerdown", (event) => {
    if (!canvas.contains(event.target)) setActive(false);
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") setActive(false); });
  const view = panZoom(svg, isActive);

  const layersButton = button(t.layers, null, () => toggleLayers(layerList.hidden));
  layersButton.ariaExpanded = "false";
  function toggleLayers(open) {
    layerList.hidden = !open;
    layersButton.ariaExpanded = String(open);
  }

  const pdf = button(t.pdf, t.pdfTitle, async () => {
    pdf.disabled = true;
    error.hidden = true;
    const result = await request({ type: "pdf", id, hidden: [...hidden].map((l) => l.name) });
    pdf.disabled = false;
    if (result.error) {
      console.error(result.detail);
      error.hidden = false;
      return;
    }
    save(new Blob([result.pdf], { type: "application/pdf" }), name.replace(/\.dxf$/i, ".pdf"));
    track("pdf");
  });

  const full = button(t.fullScreen, null, () => {
    if (document.fullscreenElement === panel) document.exitFullscreen();
    else panel.requestFullscreen();
  });
  full.hidden = !document.fullscreenEnabled;
  panel.addEventListener("fullscreenchange", () => {
    full.textContent = document.fullscreenElement === panel ? t.exitFullScreen : t.fullScreen;
    setActive(document.fullscreenElement === panel);
  });

  const spacer = Object.assign(document.createElement("span"), { className: "spacer" });
  controls.append(
    layersButton,
    pdf,
    spacer,
    button("−", t.zoomOut, () => view.zoom(1 / 0.6)),
    button("+", t.zoomIn, () => view.zoom(0.6)),
    button(t.zoomFit, null, view.fit),
    full,
  );
}

function reportForm(file, result) {
  const wrapper = document.createElement("div");
  wrapper.className = "report";
  // Only drawings help; a DWG dropped by mistake isn't worth uploading
  if (!/\.skf$/i.test(file.name)) return wrapper;
  const problem = result.error || Object.keys(result.report).some(isWarning);
  const form = document.createElement("form");
  form.hidden = true;
  const open = button(problem ? t.reportProblem : t.reportLooksWrong, null, () => {
    open.hidden = true;
    form.hidden = false;
    comment.focus();
  });
  open.className = "report-open";

  const title = Object.assign(document.createElement("p"), {
    className: "report-title", textContent: t.reportTitle(file.name) });
  const note = document.createElement("p");
  note.textContent = t.reportNote;
  const comment = document.createElement("textarea");
  comment.name = "comment";
  comment.rows = 2;
  const contact = document.createElement("input");
  contact.name = "contact";
  contact.type = "email";
  contact.autocomplete = "email";
  const field = (text, control) => {
    const label = Object.assign(document.createElement("label"), { textContent: text });
    label.append(control);
    return label;
  };
  const message = document.createElement("p");
  message.className = "report-message";
  const send = document.createElement("button");
  send.type = "submit";
  send.textContent = t.reportSend;
  const cancel = button(t.reportCancel, null, () => {
    form.hidden = true;
    open.hidden = false;
  });
  const actions = document.createElement("div");
  actions.className = "report-actions";
  actions.append(send, cancel);
  form.append(title, note, field(t.reportComment, comment), field(t.reportContact, contact), actions,
    message);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    data.append("file", file, file.name);
    const { error, detail, report } = result;
    data.append("result", JSON.stringify(error ? { error, detail } : report));
    send.disabled = true;
    message.textContent = t.reportSending;
    try {
      const response = await fetch("api/report", { method: "POST", body: data });
      if (response.status === 429) {
        message.textContent = t.reportBusy;
        send.disabled = false;
        return;
      }
      if (!response.ok) throw new Error(await response.text());
      track("report", { result: result.error ?? "converted" });
      wrapper.replaceChildren(Object.assign(document.createElement("p"), {
        className: "report-message", textContent: t.reportThanks }));
    } catch (failure) {
      console.error(failure);
      message.textContent = t.reportFailed;
      send.disabled = false;
    }
  });
  wrapper.append(open, form);
  return wrapper;
}

function button(label, title, action) {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  if (title) element.title = element.ariaLabel = title;
  element.addEventListener("click", action);
  return element;
}

// Zoom and pan by changing the viewBox, so the browser redraws crisp vectors at any zoom
function panZoom(svg, isActive) {
  const box = svg.viewBox.baseVal;
  const home = { x: box.x, y: box.y, width: box.width, height: box.height };
  const pointers = new Map();

  function fit() {
    const rect = svg.getBoundingClientRect();
    const scale = Math.max(home.width / rect.width, home.height / rect.height);
    box.width = rect.width * scale;
    box.height = rect.height * scale;
    box.x = home.x + (home.width - box.width) / 2;
    box.y = home.y + (home.height - box.height) / 2;
  }

  function zoomAt(clientX, clientY, factor) {
    const rect = svg.getBoundingClientRect();
    const x = box.x + ((clientX - rect.left) / rect.width) * box.width;
    const y = box.y + ((clientY - rect.top) / rect.height) * box.height;
    box.x = x - (x - box.x) * factor;
    box.y = y - (y - box.y) * factor;
    box.width *= factor;
    box.height *= factor;
  }

  function zoom(factor) {
    const rect = svg.getBoundingClientRect();
    zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
  }

  svg.addEventListener("wheel", (event) => {
    // Ctrl is also how trackpad pinches arrive
    if (!isActive() && !event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    zoomAt(event.clientX, event.clientY, Math.exp(event.deltaY * 0.0015));
  }, { passive: false });

  svg.addEventListener("pointerdown", (event) => {
    svg.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  });

  svg.addEventListener("pointermove", (event) => {
    const previous = pointers.get(event.pointerId);
    if (!previous) return;
    const rect = svg.getBoundingClientRect();
    if (pointers.size === 1) {
      box.x -= ((event.clientX - previous.x) / rect.width) * box.width;
      box.y -= ((event.clientY - previous.y) / rect.height) * box.height;
    } else if (pointers.size === 2) {
      const other = [...pointers.entries()].find(([pid]) => pid !== event.pointerId)[1];
      const before = Math.hypot(previous.x - other.x, previous.y - other.y);
      const after = Math.hypot(event.clientX - other.x, event.clientY - other.y);
      if (before > 0 && after > 0) {
        zoomAt((event.clientX + other.x) / 2, (event.clientY + other.y) / 2, before / after);
      }
    }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  });

  for (const type of ["pointerup", "pointercancel"]) {
    svg.addEventListener(type, (event) => pointers.delete(event.pointerId));
  }

  new ResizeObserver(fit).observe(svg);
  fit();
  return { fit, zoom };
}
