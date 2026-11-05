import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";

import worker from "../src/index.js";

const SKF = new Uint8Array([0x0a, 0, 0, 0, 0, 0x0b, 3, 0x34, 0x31, 0x33]);

let env, ctx, stored, emails, points, allowed;

beforeEach(() => {
  stored = {};
  emails = [];
  points = [];
  allowed = true;
  const pending = [];
  ctx = { waitUntil: (promise) => pending.push(promise), settled: () => Promise.all(pending) };
  env = {
    ASSETS: { fetch: async () => new Response("asset") },
    REPORTS: { put: async (key, value) => { stored[key] = value; } },
    REPORT_LIMIT: { limit: async () => ({ success: allowed }) },
    REPORT_EMAIL: "us@example.com",
    EMAIL: { send: async (message) => { emails.push(message); return { messageId: "1" }; } },
    EVENTS: { writeDataPoint: (point) => points.push(point) },
  };
});

function post(path, body, headers = {}) {
  return worker.fetch(new Request(`https://skf2dxf.com${path}`, { method: "POST", body, headers }),
    env, ctx);
}

function reportForm({ bytes = SKF, name = "plan.skf", contact = "" } = {}) {
  const form = new FormData();
  form.append("file", new File([bytes], name));
  form.append("comment", "hatch is missing");
  form.append("contact", contact);
  form.append("result", '{"line": 3}');
  return form;
}

describe("/api/report", () => {
  test("stores the drawing and what the converter said", async () => {
    const response = await post("/api/report", reportForm());
    assert.equal(response.status, 200);
    const keys = Object.keys(stored);
    assert.equal(keys.length, 2);
    const info = JSON.parse(stored[keys.find((k) => k.startsWith("info:"))]);
    assert.deepEqual(info, { name: "plan.skf", size: SKF.length, comment: "hatch is missing",
      contact: "", result: '{"line": 3}' });
  });

  test("emails us about it, replying to the sender when they left an address", async () => {
    await post("/api/report", reportForm({ contact: "ana@example.com" }));
    await ctx.settled();
    assert.equal(emails.length, 1);
    assert.equal(emails[0].to, "us@example.com");
    assert.equal(emails[0].replyTo, "ana@example.com");
    assert.match(emails[0].subject, /plan\.skf/);
    assert.match(emails[0].text, /hatch is missing/);
  });

  test("doesn't set a reply address from something that isn't one", async () => {
    await post("/api/report", reportForm({ contact: "call me" }));
    await ctx.settled();
    assert.equal(emails[0].replyTo, undefined);
  });

  test("still succeeds when the email can't be sent", async () => {
    env.EMAIL.send = async () => { throw new Error("not verified"); };
    const response = await post("/api/report", reportForm());
    await ctx.settled();
    assert.equal(response.status, 200);
  });

  test("rejects files that aren't AutoSketch drawings", async () => {
    const response = await post("/api/report", reportForm({ bytes: new Uint8Array([0x50, 0x4b]) }));
    assert.equal(response.status, 400);
    assert.deepEqual(stored, {});
  });

  test("rejects other file names", async () => {
    const response = await post("/api/report", reportForm({ name: "plan.dwg" }));
    assert.equal(response.status, 400);
  });

  test("turns away senders over the rate limit", async () => {
    allowed = false;
    const response = await post("/api/report", reportForm());
    assert.equal(response.status, 429);
    assert.deepEqual(stored, {});
  });
});

describe("/api/event", () => {
  const send = (body) => post("/api/event", JSON.stringify(body));

  test("counts a conversion", async () => {
    const response = await send({ name: "convert", result: "warnings", version: "413 v10.0",
      warnings: "unknown hatch pattern WEAVE", lang: "es", sizeKb: 120, count: 4000 });
    assert.equal(response.status, 204);
    assert.deepEqual(points, [{
      indexes: ["convert"],
      blobs: ["convert", "warnings", "413 v10.0", "unknown hatch pattern WEAVE", "es", ""],
      doubles: [120, 4000],
    }]);
  });

  test("ignores events it doesn't know", async () => {
    const response = await send({ name: "anything" });
    assert.equal(response.status, 400);
    assert.deepEqual(points, []);
  });

  test("keeps fields short", async () => {
    await send({ name: "convert", warnings: "x".repeat(1000) });
    assert.equal(points[0].blobs[3].length, 300);
  });

  test("ignores bodies that aren't JSON", async () => {
    const response = await post("/api/event", "nope");
    assert.equal(response.status, 400);
  });
});

test("serves the page for everything else", async () => {
  const response = await worker.fetch(new Request("https://skf2dxf.com/"), env, ctx);
  assert.equal(await response.text(), "asset");
});
