const test = require("node:test");
const assert = require("node:assert");
const { mergeContacts } = require("./contacts_sync");

// A whatsapp-web.js Contact, reduced to the fields the merge reads.
const contact = (over = {}) => ({
  id: { _serialized: `${over.number || "254712345678"}@c.us` },
  number: "254712345678",
  name: "Jane",
  pushname: "jane",
  isMyContact: true,
  isGroup: false,
  isMe: false,
  isBlocked: false,
  ...over,
});

test("saved contacts become name -> number entries", () => {
  const { contacts, added } = mergeContacts([
    contact({ name: "Jane Doe", number: "254712345678" }),
    contact({ name: "Otieno", number: "254722000111", id: { _serialized: "254722000111@c.us" } }),
  ], {});
  assert.deepStrictEqual(contacts, { "Jane Doe": "254712345678", Otieno: "254722000111" });
  assert.strictEqual(added.length, 2);
});

test("entries already in the file are never renamed or repointed", () => {
  const { contacts, kept, added } = mergeContacts(
    [contact({ name: "Jane Doe", number: "254712345678" })],
    { Mom: "254712345678" },
  );
  // Same person, a name the owner chose: left alone, and not added twice.
  assert.deepStrictEqual(contacts, { Mom: "254712345678" });
  assert.strictEqual(kept, 1);
  assert.deepStrictEqual(added, []);
});

test("a local-format number in the file matches the international one", () => {
  const { added } = mergeContacts(
    [contact({ name: "Dad", number: "254712345678" })],
    { Dad: "0712345678" },
  );
  assert.deepStrictEqual(added, []);
});

test("only the address book is synced, not everyone who ever messaged", () => {
  const { contacts, skipped } = mergeContacts([
    contact({ name: "Stranger", isMyContact: false }),
    contact({ name: "Blocked", isBlocked: true }),
    contact({ name: "Group", isGroup: true }),
    contact({ name: "Me", isMe: true }),
  ], {});
  assert.deepStrictEqual(contacts, {});
  assert.strictEqual(skipped.not_saved, 4);
});

test("a contact with no number keeps its privacy id, which is a valid recipient", () => {
  const { contacts } = mergeContacts([
    contact({ name: "Lulu", number: undefined, id: { _serialized: "112257593794569@lid" } }),
  ], {});
  assert.deepStrictEqual(contacts, { Lulu: "112257593794569@lid" });
});

test("a contact with neither a number nor a privacy id is skipped", () => {
  const { contacts, skipped } = mergeContacts([
    contact({ number: "", id: { _serialized: "" } }),
  ], {});
  assert.deepStrictEqual(contacts, {});
  assert.strictEqual(skipped.no_number, 1);
});

test("a nameless contact is skipped rather than named after its own number", () => {
  const { contacts, skipped } = mergeContacts([
    contact({ name: "", pushname: "", shortName: "" }),
    contact({ name: "254722000111", number: "254722000111", id: { _serialized: "254722000111@c.us" } }),
  ], {});
  assert.deepStrictEqual(contacts, {});
  assert.strictEqual(skipped.no_name, 2);
});

test("two people under one name both stay reachable", () => {
  const { contacts } = mergeContacts([
    contact({ name: "Brian", number: "254712345678" }),
    contact({ name: "Brian", number: "254799885544", id: { _serialized: "254799885544@c.us" } }),
  ], {});
  assert.deepStrictEqual(contacts, { Brian: "254712345678", "Brian (5544)": "254799885544" });
});

test("names are trimmed, collapsed and cut to the length the dashboard accepts", () => {
  const { contacts } = mergeContacts([
    contact({ name: "  Jane\n\tDoe  " }),
    contact({ name: "x".repeat(90), number: "254700000001", id: { _serialized: "254700000001@c.us" } }),
  ], {});
  assert.ok(contacts["Jane Doe"]);
  assert.ok(Object.keys(contacts).every((n) => n.length <= 60));
});

test("one sync cannot widen the file without bound", () => {
  const many = Array.from({ length: 12 }, (_, i) => contact({
    name: `P${i}`,
    number: `25470000${String(i).padStart(4, "0")}`,
    id: { _serialized: `25470000${String(i).padStart(4, "0")}@c.us` },
  }));
  const { added, skipped } = mergeContacts(many, {}, { limit: 5 });
  assert.strictEqual(added.length, 5);
  assert.strictEqual(skipped.over_limit, 7);
});

test("syncing twice changes nothing the second time", () => {
  const list = [
    contact({ name: "Zoe", number: "254700000002", id: { _serialized: "254700000002@c.us" } }),
    contact({ name: "Abel", number: "254700000003", id: { _serialized: "254700000003@c.us" } }),
  ];
  const first = mergeContacts(list, { Mom: "254712345678" }).contacts;
  const second = mergeContacts(list, first);
  assert.deepStrictEqual(second.contacts, first);
  assert.deepStrictEqual(second.added, []);
  assert.deepStrictEqual(Object.keys(first), ["Abel", "Mom", "Zoe"]);  // sorted, so the file is readable
});

test("a missing or empty contact list is not an error", () => {
  assert.deepStrictEqual(mergeContacts(undefined, { Mom: "1" }).contacts, { Mom: "1" });
  assert.deepStrictEqual(mergeContacts([null], {}).contacts, {});
});
