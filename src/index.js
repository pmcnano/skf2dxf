const MAX_SIZE = 25 * 1024 * 1024; // KV's value limit
// Every AutoSketch drawing starts with u32 10
const SIGNATURE = [0x0a, 0, 0, 0];
const EVENTS = new Set(["convert", "zip", "preview", "pdf", "report"]);

export default {
  async fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);
    if (request.method === "POST" && pathname === "/api/report") return report(request, env, ctx);
    if (request.method === "POST" && pathname === "/api/event") return event(request, env);
    return env.ASSETS.fetch(request);
  },
};

// Stores a drawing someone chose to send, with what the converter said about it. No IP or
// other identifying data is kept; contact is whatever the person typed, if anything.
async function report(request, env, ctx) {
  const ip = request.headers.get("cf-connecting-ip") ?? "";
  if (!(await env.REPORT_LIMIT.limit({ key: ip })).success) {
    return Response.json({ error: "Too many files, try again in a minute" }, { status: 429 });
  }
  const form = await request.formData();
  const file = form.get("file");
  if (!(file instanceof File) || !/\.skf$/i.test(file.name) || file.size === 0 ||
      file.size > MAX_SIZE || !(await isDrawing(file))) {
    return Response.json({ error: "Only AutoSketch .skf files up to 25 MB" }, { status: 400 });
  }
  const field = (name, max) => String(form.get(name) ?? "").slice(0, max);
  const key = `${new Date().toISOString()}-${crypto.randomUUID().slice(0, 8)}`;
  const info = {
    name: file.name.slice(0, 200),
    size: file.size,
    comment: field("comment", 2000),
    contact: field("contact", 200),
    result: field("result", 5000),
  };
  await env.REPORTS.put(`file:${key}`, await file.arrayBuffer());
  await env.REPORTS.put(`info:${key}`, JSON.stringify(info));
  ctx.waitUntil(notify(env, key, info));
  return Response.json({ ok: true });
}

async function isDrawing(file) {
  const head = new Uint8Array(await file.slice(0, SIGNATURE.length).arrayBuffer());
  return SIGNATURE.every((byte, i) => head[i] === byte);
}

async function notify(env, key, info) {
  try {
    // Required even when the binding has a destination_address, despite Cloudflare's docs
    await env.EMAIL.send({
      to: env.REPORT_EMAIL,
      from: { email: "reports@skf2dxf.com", name: "skf2dxf" },
      replyTo: /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(info.contact) ? info.contact : undefined,
      subject: `Drawing sent: ${info.name}`,
      text: [
        `${info.name} (${Math.ceil(info.size / 1024)} KB)`,
        `Comment: ${info.comment || "-"}`,
        `Contact: ${info.contact || "-"}`,
        `Converter: ${info.result}`,
        "",
        `Key: ${key}`,
        "Pull it with: uv run python tools/pull_reports.py",
      ].join("\n"),
    });
  } catch (error) {
    console.error("report email failed", error);
  }
}

// Anonymous usage counts in Analytics Engine; the page never sends file names or contents
async function event(request, env) {
  let data;
  try {
    data = await request.json();
  } catch {
    return new Response(null, { status: 400 });
  }
  if (!EVENTS.has(data?.name)) return new Response(null, { status: 400 });
  const text = (value) => String(value ?? "").slice(0, 300);
  const number = (value) => (Number.isFinite(value) ? value : 0);
  env.EVENTS.writeDataPoint({
    indexes: [data.name],
    blobs: [data.name, text(data.result), text(data.version), text(data.warnings), text(data.lang),
      request.cf?.country ?? ""],
    doubles: [number(data.sizeKb), number(data.count)],
  });
  return new Response(null, { status: 204 });
}
