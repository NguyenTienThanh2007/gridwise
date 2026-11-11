# syntax=docker/dockerfile:1
# Build context: repository root.
FROM node:24-slim AS build
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm install --global pnpm@11.25.0
WORKDIR /src

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile

COPY apps/web apps/web
# NEXT_PUBLIC_* values are compiled into the browser bundle at build time.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_OUTPUT=standalone
RUN pnpm --filter @gridwise/web build


FROM node:24-slim AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node /src/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /src/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=node:node /src/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
