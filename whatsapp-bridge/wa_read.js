// Shapes WhatsApp's own chats and messages for the dashboard to read.
//
// Read-only on purpose: nothing here marks a chat as seen, because opening a
// thread on the dashboard should not send a read receipt to the other person.
// Nothing here is stored either — the database holds only what went through the
// agent, and these are the owner's own chats passing through on their way to
// their own screen.
//
// Free of the WhatsApp client, so the shaping and filtering can be tested
// directly. Run the tests with: npm test

const PREVIEW_CHARS = 90;
const BODY_CHARS = 4000;
const DEFAULT_CHATS = 25;
const DEFAULT_MESSAGES = 50;

// A direct chat, a privacy-id chat, or a group. Status updates, channels and
// broadcast lists are not conversations and are left out.
const CHAT_ID = /^\d+@(c\.us|lid|g\.us)$/;

/** Something to show for a message with no text of its own. */
function mediaLabel(type) {
  return {
    image: "Photo", video: "Video", sticker: "Sticker", document: "Document",
    audio: "Audio", ptt: "Voice note", location: "Location", vcard: "Contact card",
    poll_creation: "Poll", revoked: "Deleted message",
  }[type] || "Attachment";
}

const clip = (s, max) => {
  const text = String(s || "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
};

/** Fall back to the number when WhatsApp has no name for the chat. */
function chatName(chat, id) {
  const given = String(chat.name || "").replace(/\s+/g, " ").trim();
  if (given) return clip(given, 60);
  const [local, domain] = id.split("@");
  return domain === "c.us" ? local : "Unknown";
}

function shapeChats(chats, { limit = DEFAULT_CHATS } = {}) {
  return (chats || [])
    .filter((chat) => chat && chat.id && CHAT_ID.test(chat.id._serialized || ""))
    .map((chat) => {
      const id = chat.id._serialized;
      const last = chat.lastMessage;
      const body = last ? clip(last.body, PREVIEW_CHARS) : "";
      return {
        id,
        name: chatName(chat, id),
        is_group: Boolean(chat.isGroup),
        unread: Number(chat.unreadCount) || 0,
        ts: Number(last ? last.timestamp : chat.timestamp) || 0,
        preview: body || (last && last.hasMedia ? mediaLabel(last.type) : ""),
        from_me: Boolean(last && last.fromMe),
      };
    })
    // Most recently active first, which is the order WhatsApp itself shows.
    .sort((a, b) => b.ts - a.ts)
    .slice(0, Math.max(1, limit));
}

function shapeMessages(messages, { limit = DEFAULT_MESSAGES } = {}) {
  return (messages || [])
    .filter(Boolean)
    .map((msg) => ({
      id: (msg.id && (msg.id._serialized || msg.id.id)) || "",
      ts: Number(msg.timestamp) || 0,
      from_me: Boolean(msg.fromMe),
      // In a group, who in the group said it.
      author: String(msg.author || "").split("@")[0].split(":")[0] || "",
      body: clip(msg.body, BODY_CHARS),
      kind: msg.hasMedia ? mediaLabel(msg.type) : "",
    }))
    .sort((a, b) => a.ts - b.ts)   // oldest first: a thread reads downwards
    .slice(-Math.max(1, limit));
}

module.exports = {
  shapeChats, shapeMessages, mediaLabel, chatName,
  CHAT_ID, DEFAULT_CHATS, DEFAULT_MESSAGES,
};
