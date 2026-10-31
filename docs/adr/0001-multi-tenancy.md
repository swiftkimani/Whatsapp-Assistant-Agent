# ADR-0001: How this becomes multi-tenant
- Status: proposed
- Date: 2026-10-31
- Deciders: owner

## Context

Today the system is single-tenant in a way that is structural, not incidental.
Every one of these assumes exactly one person:

| Thing | How it assumes one owner |
|---|---|
| WhatsApp session | One `LocalAuth` profile on the `wa-session` volume. One linked phone |
| `ALLOWED_CONTACTS` | A process-wide env var |
| `contacts.json` | One file on a shared volume, read by path |
| `data/kb/about_me.md`, `style_examples.md` | One file each, read by path, and the prompt is built from them per process |
| SQLite (`held`, `messages`, `message_log`, `settings`, `contact_modes`) | No tenant column anywhere. `auto_reply` is one row in `settings` |
| Dashboard auth | One password hash in an env var. No user table |
| `app/live.py` | One in-process subscriber set, broadcast to everyone listening |
| `USER_NAME`, `TZ`, `QUIET_HOURS` | Env vars read at request time, global |

The hard constraint is WhatsApp itself. whatsapp-web.js drives a real browser
session per linked account: roughly 300-400 MB of Chromium and a persistent
profile **per tenant**, which cannot be pooled or shared. That single fact
decides most of the architecture — everything else is ordinary SaaS plumbing.

## Decision

Proposed: **a container per tenant, orchestrated by a small control plane**,
rather than one process serving many tenants.

```
                 ┌─────────────────────────────┐
  arie.app  ───> │ control plane               │  Postgres: tenants, users,
                 │  auth, billing, routing     │  sessions, billing
                 └──────────┬──────────────────┘
                            │ starts / stops / routes
         ┌──────────────────┼──────────────────┐
    ┌────▼─────┐       ┌────▼─────┐       ┌────▼─────┐
    │ tenant A │       │ tenant B │       │ tenant C │
    │ backend  │       │ backend  │       │ backend  │
    │ + bridge │       │ + bridge │       │ + bridge │
    │ + volume │       │ + volume │       │ + volume │
    └──────────┘       └──────────┘       └──────────┘
```

Each tenant keeps exactly today's two containers and three volumes. The
control plane owns sign-up, login, which subdomain or path maps to which
tenant, and the lifecycle of their containers.

### Why not one process, many tenants

It is the obvious instinct and it is wrong here. It would mean a tenant id
threaded through every table, every file path, the prompt cache, the live bus
and the allowlist — and then *still* one Chromium per tenant inside one
process, where a crash in anyone's session takes down everybody's. The
isolation is the point: a WhatsApp account is the most sensitive thing most
people own, and a query missing a `WHERE tenant_id = ?` leaks one person's
private messages into another's dashboard. Process boundaries make that class
of bug impossible rather than merely unlikely.

## Consequences

**Positive**
- Today's code runs nearly unchanged inside each tenant. No tenant column, no
  risk of a cross-tenant query, no shared prompt cache to get wrong.
- A tenant whose WhatsApp session breaks affects nobody else.
- Suspending a non-paying tenant is stopping a container.
- Per-tenant resource limits and per-tenant backups come free.

**Negative / trade-offs**
- **Cost per tenant is high and mostly fixed.** Chromium plus the Python image
  is roughly 600 MB-1 GB of RAM per tenant, before any traffic. On one Contabo
  box that is a handful of tenants, not hundreds. This is the number that
  decides whether the business works, and it should be measured before any of
  this is built.
- A control plane is a second system: auth, billing, orchestration, monitoring.
- Deploys become a rollout across N stacks, not one redeploy.
- Model cost is per tenant and uncapped unless metered deliberately.

**Follow-ups, in order**
1. **Measure first.** Run two full stacks on the current server and record
   idle and active RAM. Everything below depends on that number.
2. Move the per-owner settings out of env vars into the tenant's own database
   (`USER_NAME`, `ALLOWED_CONTACTS`, `QUIET_HOURS`, `TZ`), so a tenant can be
   configured without a redeploy. This is worth doing even single-tenant.
3. Replace the single password with real accounts in the control plane.
4. Meter model spend per tenant, with a cap. One tenant's bad day must not
   become an unbounded bill.
5. Only then: orchestration, sign-up, billing.

## Alternatives considered

| Option | Why not |
|---|---|
| One process, tenant id on every row | Still one Chromium per tenant, but now with shared blast radius and a whole class of cross-tenant leak bugs. Isolation is the main thing worth buying here |
| WhatsApp Business Cloud API instead of whatsapp-web.js | Removes Chromium entirely and is the *right* answer for a real product — but it is a different product. Template-approval rules, per-message pricing, a business number rather than the owner's personal one, and 24-hour reply windows. It cannot do "reply as me from my own number", which is what this system is |
| Serverless bridges, started on demand | WhatsApp sessions must stay connected to receive messages. A cold session misses them |
| One shared bridge, many accounts | whatsapp-web.js is one account per client instance; several in one process means several Chromiums in one process, which is the worst of both |

## Honest summary

The code changes are the easy part and mostly already done — the notes, the
contacts and the history all read through seams that could take a tenant.
The decision that matters is the one in Follow-up 1: what a tenant costs to
keep alive, idle. If that number is too high, the answer is not a better
architecture, it is the Business Cloud API and a different product.
