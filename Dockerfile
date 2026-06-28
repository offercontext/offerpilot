# syntax=docker/dockerfile:1

# ---- Stage 1: build the React frontend ----
FROM node:20-alpine AS web
WORKDIR /web
# Install deps first for better layer caching.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# ---- Stage 2: build the Go binary ----
FROM golang:1.22-alpine AS backend
WORKDIR /src
# modernc.org/sqlite is pure-Go (no CGO), so we can build a static binary.
ENV CGO_ENABLED=0
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Embed the freshly built frontend dist so the binary's adjacent web/dist
# lookup resolves inside the container.
COPY --from=web /web/dist ./web/dist
RUN go build -trimpath -ldflags="-s -w" -o /out/oc ./cmd/oc

# ---- Stage 3: minimal runtime ----
FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata && \
    adduser -D -h /app -s /bin/sh offerpilot
WORKDIR /app
COPY --from=backend /out/oc /app/oc
COPY web/dist /app/web/dist

# Data directory: mounted volume persists SQLite + config.json.
ENV OFFERPILOT_DATA=/data
USER offerpilot
EXPOSE 8080
VOLUME ["/data"]
ENTRYPOINT ["/app/oc"]
CMD ["start", "--port", "8080"]