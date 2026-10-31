import { createServer } from "node:http";
import worker from "./takes.js";

const objects = new Map();
const bucket = {
  async put(key, body) { objects.set(key, new Uint8Array(body)); },
  async get(key) { return objects.has(key) ? { body: objects.get(key) } : null; },
  async delete(key) { objects.delete(key); },
  async list({ prefix = "", limit = 1000 } = {}) {
    const keys = [...objects.keys()].filter((key) => key.startsWith(prefix)).sort().slice(0, limit);
    return { objects: keys.map((key) => ({ key })), truncated: false };
  },
};
const env = { TAKES: bucket, CODES: process.env.CODES || "", ADMIN: process.env.ADMIN || "" };
const port = Number(process.env.PORT || 8787);

createServer(async (incoming, outgoing) => {
  const chunks = [];
  for await (const chunk of incoming) chunks.push(chunk);
  const body = ["GET", "HEAD"].includes(incoming.method) ? undefined : Buffer.concat(chunks);
  const response = await worker.fetch(new Request(`http://localhost:${port}${incoming.url}`, { method: incoming.method, headers: incoming.headers, body }), env);
  outgoing.writeHead(response.status, Object.fromEntries(response.headers));
  outgoing.end(Buffer.from(await response.arrayBuffer()));
}).listen(port, "127.0.0.1", () => console.log(`takes worker on http://127.0.0.1:${port}`));
