// Who is allowed to reach the assistant. This is the security boundary of the
// whole system: everything that gets past it is transcribed, stored, and sent
// to a model, so it is worth being able to test in isolation.
//
// Kept free of module-level state so the rules can be exercised directly;
// index.js reads the environment and passes the result in.

/**
 * @param {string} chatId        e.g. "2547...@c.us", "...@lid", "...@g.us"
 * @param {object} opts
 * @param {string[]} opts.allowed  allowlisted numbers, and/or the word
 *        "contacts" meaning everyone in the address book
 * @param {boolean} opts.allowGroups
 * @param {() => string[]} [opts.addressBook] numbers from contacts.json,
 *        only called when "contacts" is listed
 * @param {() => Promise<{number?: string}|null>} [opts.resolveContact]
 *        resolves an @lid privacy id to a real contact; only called for @lid
 * @returns {Promise<{allowed: boolean, number: string, kind: string, reason: string}>}
 */
async function checkAllowed(chatId, { allowed, allowGroups, resolveContact, addressBook } = {}) {
  const from = String(chatId || "");
  const entries = (allowed || []).map((n) => String(n).trim()).filter(Boolean);

  // "contacts" stands for everyone in the address book. Hand-typing numbers
  // does not survive contact sync, and the alternative people reach for —
  // leaving this empty — answers complete strangers.
  const usesAddressBook = entries.some((e) => e.toLowerCase() === "contacts");
  const list = entries.map((n) => n.replace(/\D/g, "")).filter(Boolean);
  if (usesAddressBook && typeof addressBook === "function") {
    try {
      for (const number of addressBook()) {
        const digits = String(number).replace(/\D/g, "");
        if (digits) list.push(digits);
      }
    } catch {
      // An unreadable contacts.json must not quietly widen the allowlist.
      return { allowed: false, number: "", kind: "unknown", reason: "address_book_unreadable" };
    }
  }
  const kind = from.endsWith("@g.us") ? "group" : from.endsWith("@lid") ? "lid" : "direct";

  // Drop the device suffix BEFORE stripping punctuation. On multi-device
  // accounts WhatsApp sends "2547...:12@c.us", and removing non-digits first
  // would splice the "12" onto the number and silently never match.
  let number = from.split("@")[0].split(":")[0].replace(/\D/g, "");

  if (kind === "group" && !allowGroups) {
    return { allowed: false, number, kind, reason: "groups_off" };
  }

  if (kind === "lid" && typeof resolveContact === "function") {
    try {
      const contact = await resolveContact();
      if (contact && contact.number) number = String(contact.number).replace(/\D/g, "");
    } catch {
      return { allowed: false, number, kind, reason: "lid_unresolved" };
    }
  }

  if (entries.length === 0) return { allowed: true, number, kind, reason: "allowlist_empty" };
  if (list.length === 0) {
    // "contacts" was asked for and the address book is empty: nobody, rather
    // than everybody. Failing open here would be the worst possible default.
    return { allowed: false, number, kind, reason: "address_book_empty" };
  }

  // Compare on the last 9 digits as well as the whole number. The same person
  // reaches you as 254712345678, 0712345678 or +254 712 345 678 depending on
  // how the sender's phone stored it, and all three are the same human.
  const tail = (n) => n.slice(-9);
  const hit = list.some((n) => n === number || (number.length >= 9 && tail(n) === tail(number)));
  return { allowed: hit, number, kind, reason: hit ? "allowed" : "not_in_allowlist" };
}

module.exports = { checkAllowed };
