// Turns WhatsApp's own address book into contacts.json entries.
//
// contacts.json is the list of people the dashboard and the assistant are
// allowed to send TO, so a sync only ever ADDS. An entry already in the file is
// never renamed, repointed or removed, and somebody already in the file under a
// name you chose ("Mom") is not added a second time under the name WhatsApp
// happens to hold for them.
//
// Free of I/O and of the WhatsApp client, so the rules can be exercised
// directly: bridge_api.js reads the file, calls this, and writes the result.
// Run the tests with: npm test

const MAX_NAME = 60;        // app/dashboard.py caps the contact field at 60
const DEFAULT_LIMIT = 500;  // a bound on how far one sync can widen the file

const digitsOf = (s) => String(s || "").replace(/\D/g, "");

// Compare on the last 9 digits: the same person is stored as 254712345678 by
// one phone and 0712345678 by another, and both are the same human.
const tail = (d) => d.slice(-9);

function cleanName(raw) {
  return String(raw || "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")   // control characters
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, MAX_NAME)
    .trim();
}

/** What to store as the recipient: a phone number, or an "@lid" chat id. */
function entryFor(contact) {
  const number = digitsOf(contact.number);
  if (number.length >= 7) return number;
  // Some contacts have no number attached, only an opaque privacy id. That is
  // still a valid recipient, and contacts.json takes a full chat id as-is.
  const id = (contact.id && contact.id._serialized) || "";
  return /^\d+@lid$/.test(id) ? id : null;
}

/**
 * @param {Array<object>} waContacts  whatsapp-web.js Contact objects
 * @param {Record<string,string>} existing  contacts.json as it stands
 * @param {{limit?: number}} [opts]
 * @returns {{contacts: Record<string,string>, added: string[], kept: number,
 *            skipped: Record<string, number>}}
 */
function mergeContacts(waContacts, existing, { limit = DEFAULT_LIMIT } = {}) {
  const kept = { ...(existing || {}) };
  const skipped = { not_saved: 0, no_number: 0, no_name: 0, already_known: 0, over_limit: 0 };

  // What the file already covers, so a sync cannot duplicate a person.
  const takenNames = new Set(Object.keys(kept).map((n) => n.trim().toLowerCase()));
  const knownIds = new Set();
  const knownTails = new Set();
  for (const value of Object.values(kept)) {
    const v = String(value).trim();
    if (v.includes("@")) knownIds.add(v.toLowerCase());
    else if (digitsOf(v).length >= 9) knownTails.add(tail(digitsOf(v)));
  }

  const added = {};
  for (const contact of waContacts || []) {
    if (!contact || contact.isGroup || contact.isMe) { skipped.not_saved += 1; continue; }
    // Only the address book. Without this every stranger who ever messaged the
    // account becomes someone the dashboard may message back.
    if (!contact.isMyContact || contact.isBlocked) { skipped.not_saved += 1; continue; }

    const entry = entryFor(contact);
    if (!entry) { skipped.no_number += 1; continue; }

    const known = entry.includes("@")
      ? knownIds.has(entry.toLowerCase())
      : digitsOf(entry).length >= 9 && knownTails.has(tail(digitsOf(entry)));
    if (known) { skipped.already_known += 1; continue; }

    // The name you saved comes first; pushname is what they call themselves.
    let name = cleanName(contact.name || contact.pushname || contact.shortName);
    if (!name || digitsOf(name) === digitsOf(entry)) { skipped.no_name += 1; continue; }

    // Two different people saved under one name: keep both reachable by
    // distinguishing the second with the last four digits of their number.
    if (takenNames.has(name.toLowerCase())) {
      const suffix = ` (${digitsOf(entry).slice(-4) || "2"})`;
      name = cleanName(name.slice(0, MAX_NAME - suffix.length)) + suffix;
      if (takenNames.has(name.toLowerCase())) { skipped.already_known += 1; continue; }
    }

    if (Object.keys(added).length >= limit) { skipped.over_limit += 1; continue; }

    added[name] = entry;
    takenNames.add(name.toLowerCase());
    if (entry.includes("@")) knownIds.add(entry.toLowerCase());
    else knownTails.add(tail(digitsOf(entry)));
  }

  // Sorted output, so the file stays readable and a sync that changes nothing
  // produces an identical file.
  const all = { ...kept, ...added };
  const contacts = {};
  for (const name of Object.keys(all).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()))) {
    contacts[name] = all[name];
  }

  return { contacts, added: Object.keys(added), kept: Object.keys(kept).length, skipped };
}

module.exports = { mergeContacts, cleanName, DEFAULT_LIMIT, MAX_NAME };
