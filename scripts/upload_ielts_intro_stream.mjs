/**
 * Upload optimized hero IELTS intro to Cloudflare Stream via tus
 * (required for files that may exceed basic POST 200MB limit).
 *
 * Endpoint: POST /accounts/{id}/stream  (tus)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const require = createRequire(path.join(repoRoot, "admin/web/package.json"));
const tus = require("tus-js-client");

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  for (const line of fs.readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

loadEnvFile(path.join(repoRoot, "backend/.env"));

const VIDEO = path.join(repoRoot, "Video", "optimized", "ielts-intro-hero.mp4");
const TAG = "ielts-intro";
const TITLE = "IELTS intro";
const ACCOUNT_ID = (process.env.CLOUDFLARE_ACCOUNT_ID || "").trim();
const TOKEN = (process.env.CLOUDFLARE_API_TOKEN || "").trim();
const CUSTOMER = (process.env.STREAM_CUSTOMER_CODE || "")
  .trim()
  .replace(/^https?:\/\//, "")
  .split(".cloudflarestream.com")[0]
  .replace(/\/$/, "");
const SUPABASE_URL = (process.env.SUPABASE_URL || "").trim();
const SUPABASE_KEY = (
  process.env.SUPABASE_SECRET_KEY ||
  process.env.SUPABASE_SERVICE_ROLE_KEY ||
  ""
).trim();

if (!fs.existsSync(VIDEO)) {
  console.error(`Missing optimized file: ${VIDEO}`);
  process.exit(1);
}
if (!ACCOUNT_ID || !TOKEN || !CUSTOMER || !SUPABASE_URL || !SUPABASE_KEY) {
  console.error("Missing required env vars");
  process.exit(1);
}

const size = fs.statSync(VIDEO).size;
console.log(`file_mb=${(size / 1024 / 1024).toFixed(1)}`);

// Chunk size must be divisible by 256 KiB; 50 MiB is recommended.
const CHUNK = 50 * 1024 * 1024;
const endpoint = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/stream`;

let mediaId = "";
console.log("uploading via tus to Stream API...");

await new Promise((resolve, reject) => {
  let lastPct = -1;
  const upload = new tus.Upload(fs.createReadStream(VIDEO), {
    endpoint,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
    },
    chunkSize: CHUNK,
    retryDelays: [0, 3000, 5000, 10000, 20000],
    uploadSize: size,
    metadata: {
      name: TITLE,
      filetype: "video/mp4",
      // max duration for this asset (2h); hero source is ~5.4 min
      maxDurationSeconds: "7200",
    },
    onError(err) {
      reject(err);
    },
    onProgress(bytesUploaded, bytesTotal) {
      const pct = bytesTotal ? Math.round((bytesUploaded / bytesTotal) * 100) : 0;
      if (pct !== lastPct && (pct % 1 === 0)) {
        lastPct = pct;
        console.log(`upload_progress=${pct}%`);
      }
    },
    onSuccess() {
      resolve();
    },
    onAfterResponse(req, res) {
      return new Promise((resDone) => {
        const header = res.getHeader("stream-media-id");
        if (header) mediaId = header;
        resDone();
      });
    },
  });
  upload.start();
});

if (!mediaId) {
  console.error("Upload finished but stream-media-id missing");
  process.exit(1);
}
console.log(`upload_done uid=${mediaId}`);

let video = null;
for (let i = 0; i < 90; i++) {
  const res = await fetch(
    `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/stream/${mediaId}`,
    { headers: { Authorization: `Bearer ${TOKEN}` } },
  );
  const body = await res.json();
  if (!body.success) {
    console.log(`poll_body=${JSON.stringify(body).slice(0, 300)}`);
  }
  video = body.result || null;
  const state = String(video?.status?.state || "");
  console.log(`stream_status=${state || "unknown"}`);
  if (["ready", "complete", "error", "failed"].includes(state.toLowerCase())) break;
  await new Promise((r) => setTimeout(r, 4000));
}

const state = String(video?.status?.state || "processing").toLowerCase();
const status = ["ready", "complete"].includes(state)
  ? "ready"
  : ["error", "failed"].includes(state)
    ? "error"
    : "processing";
const durationSec = Number(video?.duration || 0);
const durationMin = durationSec > 0 ? Math.max(1, Math.ceil(durationSec / 60)) : 6;
const playback = `https://${CUSTOMER}.cloudflarestream.com/${mediaId}/iframe`;
const poster = `https://${CUSTOMER}.cloudflarestream.com/${mediaId}/thumbnails/thumbnail.jpg?time=2s&height=720`;

const row = {
  tag: TAG,
  title: TITLE,
  stream_uid: mediaId,
  playback_url: playback,
  duration_min: durationMin,
  status,
  updated_at: new Date().toISOString(),
};

const upsertRes = await fetch(`${SUPABASE_URL}/rest/v1/stream_videos?on_conflict=tag`, {
  method: "POST",
  headers: {
    apikey: SUPABASE_KEY,
    Authorization: `Bearer ${SUPABASE_KEY}`,
    "Content-Type": "application/json",
    Prefer: "resolution=merge-duplicates,return=representation",
  },
  body: JSON.stringify(row),
});
const upsertText = await upsertRes.text();
if (!upsertRes.ok) {
  console.error(`supabase_upsert_failed ${upsertRes.status} ${upsertText}`);
  process.exit(1);
}

// Write frontend env hint for hero wiring
const envSnippet = [
  `# Hero Stream avatar (ielts-intro) — generated by upload_ielts_intro_stream.mjs`,
  `NEXT_PUBLIC_HERO_STREAM_UID=${mediaId}`,
  `NEXT_PUBLIC_HERO_STREAM_CUSTOMER=${CUSTOMER}`,
  `NEXT_PUBLIC_HERO_STREAM_POSTER=${poster}`,
].join("\n");
fs.writeFileSync(path.join(repoRoot, "frontend/.env.hero.stream.local"), `${envSnippet}\n`);

console.log(
  JSON.stringify(
    {
      uid: mediaId,
      playback_url: playback,
      poster,
      status,
      duration_min: durationMin,
      saved: true,
    },
    null,
    2,
  ),
);
console.log("DONE");
