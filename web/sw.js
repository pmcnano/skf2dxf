// Keeps the page working offline: the app's own files are fetched fresh when online and
// served from the cache otherwise; Pyodide's versioned files never change, so cache first.
const APP_CACHE = "skf2dxf-app";
const CDN_CACHE = "skf2dxf-pyodide-0.27.7";
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const PACKAGES = ["micropip", "numpy", "pyparsing", "fonttools", "typing-extensions", "pillow"];
const APP_FILES = ["./", "app.js", "style.css", "worker.js", "skf2dxf.py", "preview.py", "patterns.json",
  "fonts/DejaVuSans.ttf", "vendor/ezdxf-1.4.5-py3-none-any.whl", "manifest.webmanifest",
  "icon-192.png", "icon-512.png"];

async function pyodideFiles() {
  const lock = await (await fetch(`${PYODIDE}pyodide-lock.json`)).json();
  const names = new Set();
  const add = (name) => {
    if (names.has(name)) return;
    names.add(name);
    lock.packages[name].depends.forEach(add);
  };
  PACKAGES.forEach(add);
  const files = [...names].map((name) => lock.packages[name].file_name);
  return ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip",
    "pyodide-lock.json", ...files].map((file) => PYODIDE + file);
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    await (await caches.open(APP_CACHE)).addAll(APP_FILES);
    await (await caches.open(CDN_CACHE)).addAll(await pyodideFiles());
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin === location.origin) {
    event.respondWith(networkFirst(request));
  } else if (url.href.startsWith(PYODIDE)) {
    event.respondWith(cacheFirst(request));
  }
});

async function networkFirst(request) {
  const cache = await caches.open(APP_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (error) {
    return (await cache.match(request, { ignoreSearch: true })) ?? Response.error();
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CDN_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok || response.type === "opaque") cache.put(request, response.clone());
  return response;
}
