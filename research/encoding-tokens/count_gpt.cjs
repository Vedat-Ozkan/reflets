const { get_encoding } = require("tiktoken");
const fs = require("fs"), path = require("path");
const enc = get_encoding("o200k_base");
console.log("file\tgpt_tokens\tchars");
for (const f of process.argv.slice(2)) {
  const t = fs.readFileSync(f, "utf8");
  console.log(`${path.basename(f)}\t${enc.encode(t).length}\t${t.length}`);
}
