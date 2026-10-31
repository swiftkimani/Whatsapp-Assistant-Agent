// Local API so the Python backend can ask the bridge to send things.
// Binds loopback by default, needs a secret header, and can only message
// names listed in contacts.json (never a number taken from the request).

const fs = require("fs");
const http = require("http");
const path = require("path");
const { Location } = require("whatsapp-web.js");
const { mergeContacts, DEFAULT_LIMIT } = require("./contacts_sync");

// Project root by default; CONTACTS_FILE moves it so the backend and the bridge
// can share one copy when they run as separate containers.
const CONTACTS_FILE = process.env.CONTACTS_FILE
  || path.resolve(__dirname, "..", "contacts.json");
const ROUTES = ["/send-text", "/send-location", "/send-reply", "/sync-contacts"];
let started = false; // "ready" can fire again after a reconnect

// Re-read on every request so edits to contacts.json apply without a restart.
function readContacts() {
  try {
    const raw = JSON.parse(fs.readFileSync(CONTACTS_FILE, "utf-8"));
    return Object.fromEntries(Object.entries(raw).map(([k, v]) => [String(k), String(v)]));
  } catch {
    return {};   // missing or hand-edited into invalid JSON: treat as empty
  }
}

// Written via a temporary file in the same directory and renamed over the old
// one, so a sync interrupted halfway cannot leave a truncated recipient list
// behind — a half-written file is an unparseable one, and the assistant would
// then have nobody it is allowed to message.
function writeContacts(contacts) {
  const tmp = `${CONTACTS_FILE}.${process.pid}.tmp`;
  fs.mkdirSync(path.dirname(CONTACTS_FILE), { recursive: true });
  fs.writeFileSync(tmp, `${JSON.stringify(contacts, null, 2)}\n`, "utf-8");
  fs.renameSync(tmp, CONTACTS_FILE);
}

function findEntry(name) {
  const wanted = String(name || "").trim().toLowerCase();
  for (const [key, value] of Object.entries(readContacts())) {
    if (key.trim().toLowerCase() === wanted) return value.trim();
  }
  return null;
}

function startBridgeApi(client) {
  if (started) return;

  const token = process.env.BRIDGE_API_TOKEN;
  const port = Number(process.env.BRIDGE_API_PORT || 3001);
  if (!token) {
    console.error("BRIDGE_API_TOKEN is not set - send API disabled.");
    return;
  }
  started = true;

  const server = http.createServer((req, res) => {
    const reply = (code, obj) => {
      res.writeHead(code, { "Content-Type": "application/json" });
      res.end(JSON.stringify(obj));
    };

    if (req.method !== "POST" || !ROUTES.includes(req.url)) return reply(404, { error: "not found" });
    if (req.headers["x-bridge-token"] !== token) return reply(401, { error: "unauthorized" });

    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 20000) req.destroy();
    });
    req.on("end", async () => {
      try {
        const data = body ? JSON.parse(body) : {};   // /sync-contacts needs no body

        if (req.url === "/send-reply") {
          // Reply to someone who messaged us. The backend takes chat_id from its own
          // database, never from the browser, and group chats are refused here.
          const chatId = String(data.chat_id || "");
          const text = String(data.text || "").trim();
          if (!/^\d+@(c\.us|lid)$/.test(chatId)) return reply(400, { error: "bad chat id" });
          if (!text || text.length > 4000) return reply(400, { error: "bad text" });
          await client.sendMessage(chatId, text);
          console.log("[send] /send-reply");
          return reply(200, { status: "sent" });
        }

        if (req.url === "/sync-contacts") {
          // Copy the phone's own address book into contacts.json. Only ever
          // adds: see contacts_sync.js for what is skipped and why.
          const limit = Number(process.env.CONTACTS_SYNC_LIMIT || DEFAULT_LIMIT);
          const before = readContacts();
          const result = mergeContacts(await client.getContacts(), before, { limit });
          if (result.added.length) writeContacts(result.contacts);
          // Counts only: a name or a number here would put the owner's address
          // book in the host's logs.
          console.log(`[sync] contacts added=${result.added.length} kept=${result.kept} `
            + Object.entries(result.skipped).map(([k, v]) => `${k}=${v}`).join(" "));
          return reply(200, {
            status: "ok",
            added: result.added.length,
            names: result.added,
            total: Object.keys(result.contacts).length,
            skipped: result.skipped,
          });
        }

        const entry = findEntry(data.contact);
        if (!entry) return reply(400, { error: "unknown contact" });

        let chatId = entry; // a full id like 112257593794569@lid is used as-is
        if (!entry.includes("@")) {
          // plain phone number: ask WhatsApp for the matching id
          const wid = await client.getNumberId(entry.replace(/\D/g, ""));
          if (!wid) return reply(404, { error: "number is not on WhatsApp" });
          chatId = wid._serialized || wid.$1; // WhatsApp renamed _serialized to $1 in July 2026
        }

        if (req.url === "/send-text") {
          const text = String(data.text || "").trim();
          if (!text || text.length > 4000) return reply(400, { error: "bad text" });
          await client.sendMessage(chatId, text);
        } else {
          const { latitude, longitude } = data;
          if (
            !Number.isFinite(latitude) || !Number.isFinite(longitude) ||
            Math.abs(latitude) > 90 || Math.abs(longitude) > 180
          ) return reply(400, { error: "bad coordinates" });

          const mapsUrl = `https://maps.google.com/?q=${latitude},${longitude}`;
          try {
            await client.sendMessage(chatId, new Location(latitude, longitude, { name: "My location", url: mapsUrl }));
          } catch (err) {
            console.error("Pin failed, sending a map link instead:", err.stack || err);
            await client.sendMessage(chatId, mapsUrl);
          }
        }
        console.log(`[send] ${req.url} -> "${data.contact}"`); // no message text or coordinates in logs
        reply(200, { status: "sent" });
      } catch (err) {
        console.error(`${req.url} failed:`, err.stack || err);
        reply(500, { error: "request failed" });
      }
    });
  });

  // Loopback by default, so on a laptop nothing off the machine can reach it.
  // Under compose the backend is a different host, so BRIDGE_API_HOST is set to
  // 0.0.0.0 there — the port is never published outside the compose network and
  // every request still has to carry the shared token.
  const host = process.env.BRIDGE_API_HOST || "127.0.0.1";
  server.listen(port, host, () => console.log(`Bridge API on ${host}:${port}`));
}

module.exports = { startBridgeApi };