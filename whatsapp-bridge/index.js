// Thin WhatsApp connection layer.
// All "thinking" (RAG, LLM, STT, TTS, vision) happens in the Python backend.
// This file only: receives messages, forwards them, sends back the reply.

const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const axios = require("axios");
const fs = require("fs");
const path = require("path");
const { startBridgeApi } = require("./bridge_api");

// Load the SAME .env file the Python backend uses, from the project root
// (one level up from whatsapp-bridge/).
require("dotenv").config({ path: path.resolve(__dirname, "..", ".env") });

// PHASE 1: leave this true to test the WhatsApp connection alone, with no
// Python backend involved — it just echoes whatever you send back to you.
// PHASE 2: flip to false once main.py is running, to route through the
// real agent instead.
const ECHO_ONLY = false;

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000/webhook";
const ALLOW_GROUPS = (process.env.ALLOW_GROUPS || "false").toLowerCase() === "true";
const ALLOWED_CONTACTS = (process.env.ALLOWED_CONTACTS || "")
  .split(",")
  .map((c) => c.trim())
  .filter(Boolean);

// Applied BEFORE anything else, in both echo mode and real mode.
// Some contacts show up as an opaque "@lid" privacy ID instead of their
// real phone number ("@c.us") — this resolves those back to a phone
// number first, so ALLOWED_CONTACTS only ever needs to list phone numbers.
async function checkAllowed(msg) {
  const from = msg.from;
  let number = from.split("@")[0];
  if (from.endsWith("@g.us") && !ALLOW_GROUPS) return { allowed: false, number };

  if (from.endsWith("@lid")) {
    try {
      const contact = await msg.getContact();
      if (contact && contact.number) number = contact.number.replace(/\D/g, ""); // digits only
    } catch (err) {
      console.error("Could not resolve @lid contact to a phone number:", err.message);
    }
  }

  if (ALLOWED_CONTACTS.length === 0) return { allowed: true, number }; // open: tighten before going live
  return { allowed: ALLOWED_CONTACTS.includes(number), number };
}

const puppeteerConfig = {
  headless: true,
  args: [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--no-first-run",
    "--no-zygote",
  ],
};
if (process.env.PUPPETEER_EXECUTABLE_PATH) {
  // Set this to use an already-installed Chrome, and install with
  // PUPPETEER_SKIP_DOWNLOAD=true. Without it, puppeteer uses the browser it
  // downloads on install — which needs that download to have succeeded.
  puppeteerConfig.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
}

// whatsapp-web.js drives WhatsApp Web's own internal modules, so it pins the
// exact web build it was written against. That pin goes stale: WhatsApp keeps
// serving an old build to existing sessions but REFUSES TO LINK A NEW DEVICE
// on one, which surfaces as "Couldn't link device - try again later" and looks
// like a scanning problem rather than a version problem.
//
// So fetch a current build instead of using the bundled pin. wa-version
// archives WhatsApp Web's HTML per build; {version} is substituted by the
// library. Bump WA_WEB_VERSION when linking starts failing again:
//   https://github.com/wppconnect-team/wa-version/tree/main/html
const WA_WEB_VERSION = process.env.WA_WEB_VERSION || "2.3000.1047561935-alpha";

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: puppeteerConfig,
  webVersion: WA_WEB_VERSION,
  webVersionCache: {
    type: "remote",
    remotePath: "https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/{version}.html",
  },
});
console.log(`Using WhatsApp Web version ${WA_WEB_VERSION}`);

// Linking by pairing code instead of QR. A QR has to be photographed off a
// screen before it rotates, which is roughly a 20 second window and a losing
// race when the only place it renders is a web log viewer. A pairing code is
// eight characters, lasts about three minutes, and is typed in by hand.
// Set PAIRING_NUMBER to the number of the account being linked, digits only.
const PAIRING_NUMBER = (process.env.PAIRING_NUMBER || "").replace(/\D/g, "");
let pairingRequested = false;

function announcePairingCode(code) {
  const line = "=".repeat(54);
  console.log(`\n${line}\n  PAIRING CODE: ${code}\n  On your phone: WhatsApp > Linked devices >\n  "Link with phone number instead", then type this code.\n${line}\n`);
}

client.on("qr", async (qr) => {
  if (!PAIRING_NUMBER) {
    console.log("Scan this QR code with WhatsApp > Linked devices:");
    qrcode.generate(qr, { small: true });
    return;
  }
  // The QR event is the signal that the client is ready to pair; ask once, then
  // let WhatsApp refresh the code on its own interval via the "code" event.
  if (pairingRequested) return;
  pairingRequested = true;
  try {
    announcePairingCode(await client.requestPairingCode(PAIRING_NUMBER));
  } catch (err) {
    pairingRequested = false;
    console.error("Could not request a pairing code:", err.message);
    console.log("Falling back to the QR code:");
    qrcode.generate(qr, { small: true });
  }
});

client.on("code", announcePairingCode);

// client.on("ready", () => {
//   console.log(`WhatsApp bridge is ready. ECHO_ONLY = ${ECHO_ONLY}`);
// });
client.on("ready", () => {
  console.log(`WhatsApp bridge is ready. ECHO_ONLY = ${ECHO_ONLY}`);
  startBridgeApi(client);
});

client.on("message", async (msg) => {
  try {
    if (msg.fromMe) {
      console.log(`[BLOCKED - fromMe] ${msg.from}: ${msg.body}`);
      return;
    }
    const { allowed, number } = await checkAllowed(msg);
    if (!allowed) {
      console.log(`[BLOCKED - not allowed] ${msg.from}: ${msg.body}`);
      return;
    }
    console.log(`[ALLOWED] ${msg.from}: ${msg.body}`);

    if (ECHO_ONLY) {
      await client.sendMessage(msg.from, `echo: ${msg.body}`);
      return;
    }
      const payload = {
        from: msg.from,
        number,
        body: msg.body || "",
        type: "text",
        media_base64: null,
        mimetype: null,
      };  

      console.log(`[DEBUG] type=${msg.type} hasMedia=${msg.hasMedia}`);

      if (msg.hasMedia && (msg.type === "ptt" || msg.type === "audio" || msg.type === "image")) {
        try {
          const media = await msg.downloadMedia();
          if (!media || !media.data) throw new Error("downloadMedia returned nothing");
          payload.media_base64 = media.data;
          payload.mimetype = media.mimetype;
          payload.type = msg.type === "image" ? "image" : "voice";
        } catch (err) {
          console.error("downloadMedia failed:", err.stack || err);
          if (!payload.body) return; // voice note or image with no text: nothing to answer
          // image with a caption: fall through and answer the text only
        }
      }

      const { data } = await axios.post(BACKEND_URL, payload, {
        timeout: 180000,
        headers: { "x-bridge-token": process.env.BRIDGE_API_TOKEN || "" },
      });

      if (data.action === "send") {
        if (data.reply_audio_base64) {
          const voiceMedia = new MessageMedia("audio/ogg", data.reply_audio_base64);
          await client.sendMessage(msg.from, voiceMedia, { sendAudioAsVoice: true });
        } else if (data.reply_text) {
          await client.sendMessage(msg.from, data.reply_text);
        }
      } else if (data.action === "hold") {
        console.log(`Held for approval: "${data.reply_text}" — check your dashboard.`);
      }
    }   catch (err) {
      console.error("Error handling message:", err.stack || err);
    } 
});

//     const payload = {
//       from: msg.from,
//       body: msg.body || "",
//       type: "text",
//       media_base64: null,
//       mimetype: null,
//     };

//     if (msg.hasMedia && (msg.type === "ptt" || msg.type === "audio" || msg.type === "image")) {
//       const media = await msg.downloadMedia();
//       payload.media_base64 = media.data;
//       payload.mimetype = media.mimetype;
//       payload.type = msg.type === "image" ? "image" : "voice";
//     }

//     const { data } = await axios.post(BACKEND_URL, payload, { timeout: 60000 });

//     if (data.action === "send") {
//       if (data.reply_audio_base64) {
//         const voiceMedia = new MessageMedia("audio/ogg", data.reply_audio_base64);
//         await client.sendMessage(msg.from, voiceMedia, { sendAudioAsVoice: true });
//       } else if (data.reply_text) {
//         await client.sendMessage(msg.from, data.reply_text);
//       }
//     } else if (data.action === "hold") {
//       console.log(`Held for approval: "${data.reply_text}" — check your dashboard.`);
//     } else {
//       // "ignore" — not on the allowlist, or a group chat with ALLOW_GROUPS off.
//       // No reply, no log spam, nothing sent back.
//     }
//   } catch (err) {
//     console.error("Error handling message:", err.message);
//   }
// });

// Chromium writes SingletonLock/Cookie/Socket into its profile, tagged with the
// hostname of the machine that created them. A container redeploy keeps the
// session volume (so the QR does not have to be scanned again) but gets a NEW
// hostname, so Chromium finds a lock belonging to "another computer", refuses
// to launch, and the bridge crash-loops without ever printing a QR.
//
// Only one bridge process ever uses this profile, so any lock found at startup
// is left over from a container that no longer exists.
function clearStaleChromiumLocks(dir) {
  const names = /^Singleton(Lock|Cookie|Socket)$/;
  let removed = 0;
  const walk = (d) => {
    let entries;
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch {
      return; // first run: the profile does not exist yet
    }
    for (const entry of entries) {
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (names.test(entry.name)) {
        try {
          fs.unlinkSync(full);
          removed += 1;
        } catch (err) {
          console.error(`Could not remove stale lock ${full}:`, err.message);
        }
      }
    }
  };
  walk(dir);
  if (removed) console.log(`Cleared ${removed} stale Chromium lock file(s) from a previous container.`);
}

clearStaleChromiumLocks(path.resolve(__dirname, ".wwebjs_auth"));

client.initialize().catch((err) => {
  console.error("Failed to start WhatsApp client:", err.message);
});