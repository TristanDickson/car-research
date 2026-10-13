// Download one file a site serves only to a real browser: start the installed Chrome normally (its own
// profile, a debugging port), open the file's link, and let Chrome run whatever check the site sets and
// download the file as it would for a person. Nothing is faked: no user-agent override, no automation
// flags, no fingerprint changes. Each step is printed; after LIMIT_S seconds the run gives up, closes the
// browser and exits 4.
//
//   node scripts/fetch-with-chrome.mjs <file url> <out path>
//
// Env: CHROME (the browser; default the usual Windows install), CHROME_PROFILE (its profile folder;
// default ~/.car-research-chrome), CHROME_PORT (default 9335). Node 22 or later (fetch, WebSocket).
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, renameSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";

const LIMIT_S = 30;
const [fileUrl, out] = process.argv.slice(2);
if (!fileUrl || !out) {
  console.error("usage: node scripts/fetch-with-chrome.mjs <file url> <out path>");
  process.exit(2);
}
const chrome = process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const profile = process.env.CHROME_PROFILE || join(homedir(), ".car-research-chrome");
const port = Number(process.env.CHROME_PORT || 9335);
const t0 = Date.now();
const log = (s) => console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s ${s}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

mkdirSync(profile, { recursive: true });
const downloads = mkdtempSync(join(tmpdir(), "car-research-download-"));
const proc = spawn(chrome, [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run",
                            "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
log(`Chrome started (pid ${proc.pid})`);

let ws = null;
let id = 0;
const pending = new Map();
const events = [];
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const i = ++id;
  pending.set(i, { resolve, reject });
  ws.send(JSON.stringify({ id: i, method, params }));
});

async function done(code, message) {
  if (message) (code ? console.error : log)(message);
  try { if (ws) await Promise.race([send("Browser.close"), sleep(2000)]); } catch { /* already closing */ }
  if (proc.exitCode === null) proc.kill();
  rmSync(downloads, { recursive: true, force: true });
  process.exit(code);
}
setTimeout(() => done(4, `gave up after ${LIMIT_S}s; last events: ${events.slice(-3).join(", ") || "none"}`), LIMIT_S * 1000);

let version = null;
while (!version) {
  try { version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); } catch { await sleep(250); }
}
ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = () => reject(new Error("could not connect to Chrome")); });
log("connected");

let finished = null;
const download = new Promise((resolve) => { finished = resolve; });
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) {
    const p = pending.get(msg.id);
    pending.delete(msg.id);
    return msg.error ? p.reject(new Error(msg.error.message)) : p.resolve(msg.result);
  }
  if (msg.method === "Browser.downloadWillBegin") { events.push("download began"); log(`download began: ${msg.params.suggestedFilename}`); }
  if (msg.method === "Browser.downloadProgress" && msg.params.state !== "inProgress") { events.push(`download ${msg.params.state}`); finished(msg.params); }
  if (msg.method === "Target.targetInfoChanged") events.push(`page at ${msg.params.targetInfo.url}`);
};

await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: downloads, eventsEnabled: true });
await send("Target.setDiscoverTargets", { discover: true });
await send("Target.createTarget", { url: fileUrl });
log(`opened ${fileUrl}`);

const result = await download;
if (result.state !== "completed") await done(1, `download ${result.state}`);
const name = readdirSync(downloads).find((f) => !f.endsWith(".crdownload"));
if (!name) await done(1, "download completed but no file was written");
mkdirSync(dirname(out), { recursive: true });
renameSync(join(downloads, name), out);
await done(0, `downloaded ${name} (${result.receivedBytes.toLocaleString("en-GB")} bytes) -> ${out}`);
