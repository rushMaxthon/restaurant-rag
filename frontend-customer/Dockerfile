# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# frontend-customer: build the Vite bundle, serve it as static files.
#
# VITE_API_BASE_URL is a BUILD ARG, not a runtime variable, and that is a
# property of Vite rather than a choice made here: `import.meta.env.*` is
# substituted into the bundle at build time. Retargeting the API therefore
# requires a rebuild — there is no runtime override, and pretending otherwise
# is how a production bundle ends up calling http://localhost:8000.
# ---------------------------------------------------------------------------

FROM node:22-alpine AS builder

WORKDIR /build

# package files first so `npm ci` is cached independently of source changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Consumed by Vite at build time. The default matches the compose topology,
# where the edge proxy serves the API from the same origin under /api — which
# also means the browser makes same-origin requests and CORS never applies.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# `npm run build` is `tsc -b && vite build`, so a type error fails the image
# build. That is intended: a bundle that does not typecheck should not ship.
RUN npm run build


# --- runtime: static files only, no node ------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
