# WhatsApp bridge: whatsapp-web.js driving a real Chromium.
#
# Two stages so git — needed only because whatsapp-web.js is pinned to a GitHub
# ref — does not ship in the runtime image.

FROM node:24-bookworm-slim AS deps
ENV PUPPETEER_SKIP_DOWNLOAD=true
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY whatsapp-bridge/package.json whatsapp-bridge/package-lock.json ./
# npm ci honours the lockfile exactly; the GitHub ref resolves through git.
RUN npm ci --omit=dev


FROM node:24-bookworm-slim

# chromium from Debian rather than Puppeteer's own download — the same choice
# that worked on the laptop, and the package brings its sandbox, fonts and
# codecs already resolved. WhatsApp Web needs the media codecs that a bare
# headless-shell build does not have.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      chromium ca-certificates fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production \
    PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Same layout as the repo, so the bridge still resolves ../contacts.json the way
# it does locally (CONTACTS_FILE overrides it in compose anyway).
WORKDIR /app/whatsapp-bridge

COPY --from=deps /build/node_modules ./node_modules
COPY whatsapp-bridge/package.json ./
COPY whatsapp-bridge/*.js ./

# .wwebjs_auth holds live credentials to the linked WhatsApp account and is a
# volume: lose it and the QR has to be scanned again.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /app/whatsapp-bridge/.wwebjs_auth /app/whatsapp-bridge/.wwebjs_cache /app/data \
 && chown -R app:app /app
USER app

CMD ["node", "index.js"]
