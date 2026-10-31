const MAX_BYTES = 2_000_000;
const MAX_FILES = 400;
const TYPES = { wav: "audio/wav", json: "application/json" };

function said(text, status) {
  return new Response(text, { status, headers: { "Content-Type": "text/plain" } });
}

export default {
  async fetch(request, env) {
    const path = new URL(request.url).pathname;
    const token = (request.headers.get("Authorization") || "").replace(/^Bearer /, "");
    const admin = Boolean(env.ADMIN) && token === env.ADMIN;
    const upload = path.match(/^\/takes\/([0-9A-Za-z-]{1,40})\.(wav|json)$/);
    if (request.method === "PUT" && upload) {
      const codes = (env.CODES || "").split(",").map((code) => code.trim()).filter(Boolean);
      if (!/^[0-9a-z-]{1,40}$/.test(token) || !codes.includes(token)) return said("unknown tester code", 403);
      const body = await request.arrayBuffer();
      if (!body.byteLength || body.byteLength > MAX_BYTES) return said("a take is between 1 byte and 2 MB", 413);
      const listed = await env.TAKES.list({ prefix: `${token}/`, limit: MAX_FILES });
      if (listed.objects.length >= MAX_FILES) return said("this tester code has sent all the takes it can", 429);
      await env.TAKES.put(`${token}/${upload[1]}.${upload[2]}`, body, { httpMetadata: { contentType: TYPES[upload[2]] } });
      return said("stored", 201);
    }
    if (!admin) return said("not found", 404);
    if (request.method === "GET" && path === "/takes") {
      const keys = [];
      let cursor;
      do {
        const listed = await env.TAKES.list({ cursor });
        keys.push(...listed.objects.map((object) => object.key));
        cursor = listed.truncated ? listed.cursor : undefined;
      } while (cursor);
      return Response.json(keys);
    }
    const stored = path.match(/^\/takes\/([0-9a-z-]{1,40}\/[0-9A-Za-z-]{1,40}\.(?:wav|json))$/);
    if (stored && request.method === "GET") {
      const object = await env.TAKES.get(stored[1]);
      return object ? new Response(object.body) : said("not found", 404);
    }
    if (stored && request.method === "DELETE") {
      await env.TAKES.delete(stored[1]);
      return said("deleted", 200);
    }
    return said("not found", 404);
  },
};
