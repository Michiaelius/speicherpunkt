// Startet eine Edge Function unter Node als kleinen Webserver (nur für Tests).
// Aufruf: node serve.mjs <port> <funktion.mjs> <SUPABASE_URL>
import http from "node:http";
import { pathToFileURL } from "node:url";

const [port, file, supabaseUrl] = process.argv.slice(2);
const env = { SUPABASE_URL: supabaseUrl };
let handler;
globalThis.Deno = { env: { get: k => env[k] }, serve: h => { handler = h; } };
await import(pathToFileURL(file).href);

const SKIP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length"]);
http.createServer(async (req, res) => {
  try {
    const chunks = []; for await (const c of req) chunks.push(c);
    const headers = new Headers();
    for (const [k, v] of Object.entries(req.headers)) if (!SKIP.has(k)) headers.set(k, Array.isArray(v) ? v.join(", ") : v);
    const hasBody = !["GET", "HEAD"].includes(req.method);
    const body = Buffer.concat(chunks);
    if (hasBody) headers.set("content-length", String(body.length));
    const r = await handler(new Request("http://127.0.0.1:" + port + req.url, { method: req.method, headers, body: hasBody ? body : undefined }));
    const out = {}; r.headers.forEach((v, k) => { out[k] = v; });
    const buf = Buffer.from(await r.arrayBuffer());
    res.writeHead(r.status, out); res.end(buf);
  } catch (e) {
    res.writeHead(599, { "content-type": "text/plain" }); res.end(String(e && e.stack || e));
  }
}).listen(Number(port), "127.0.0.1", () => console.log("bereit"));
