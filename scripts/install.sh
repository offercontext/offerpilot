#!/usr/bin/env sh
# OfferPilot one-line installer.
#
#   curl -sSL https://get.offerpilot.dev | sh
#   curl -sSL https://get.offerpilot.dev | sh -s -- --install-dir ~/.local/bin
#
# Downloads the latest released `oc` binary for the current OS/arch from GitHub
# Releases and installs it. Falls back to building from source when no matching
# release asset is available.

set -eu

REPO="offercontext/offerpilot"
INSTALL_DIR="${INSTALL_DIR:-${HOME}/.local/bin}"
INSTALL_NAME="${INSTALL_NAME:-oc}"
BUILD_FROM_SOURCE="${BUILD_FROM_SOURCE:-0}"

err() { printf '\033[31mError:\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m=>\033[0m %s\n' "$*"; }

detect() {
  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  ARCH=$(uname -m)
  case "$OS" in
    darwin) OS="darwin" ;;
    linux)  OS="linux" ;;
    mingw*|msys*|cygwin*) OS="windows" ;;
    *) err "unsupported OS: $(uname -s)"; exit 1 ;;
  esac
  case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) err "unsupported arch: $ARCH"; exit 1 ;;
  esac
  SUFFIX=""
  [ "$OS" = "windows" ] && SUFFIX=".exe"
  ASSET="oc_${OS}_${ARCH}${SUFFIX}"
}

install_release() {
  info "fetching latest release tag"
  TAG=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | grep -m1 '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
  if [ -z "$TAG" ]; then
    err "could not determine latest release tag"
    return 1
  fi
  URL="https://github.com/${REPO}/releases/download/${TAG}/${ASSET}"
  info "downloading ${ASSET} from ${TAG}"
  mkdir -p "$INSTALL_DIR"
  TMP=$(mktemp)
  if ! curl -fsSL "$URL" -o "$TMP"; then
    rm -f "$TMP"
    return 1
  fi
  chmod +x "$TMP"
  mv "$TMP" "${INSTALL_DIR}/${INSTALL_NAME}${SUFFIX}"
  info "installed ${INSTALL_NAME} to ${INSTALL_DIR}/${INSTALL_NAME}${SUFFIX}"
}

install_source() {
  info "building from source (requires Go 1.22+)"
  if ! command -v go >/dev/null 2>&1; then
    err "Go is required to build from source. Install from https://go.dev/dl/"
    return 1
  fi
  TMP=$(mktemp -d)
  git clone --depth 1 "https://github.com/${REPO}.git" "$TMP"
  ( cd "$TMP" && go build -o "oc${SUFFIX}" ./cmd/oc )
  mkdir -p "$INSTALL_DIR"
  mv "$TMP/oc${SUFFIX}" "${INSTALL_DIR}/${INSTALL_NAME}${SUFFIX}"
  chmod +x "${INSTALL_DIR}/${INSTALL_NAME}${SUFFIX}"
  rm -rf "$TMP"
  info "built and installed ${INSTALL_NAME} to ${INSTALL_DIR}/${INSTALL_NAME}${SUFFIX}"
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --install-dir) INSTALL_DIR="$2"; shift 2 ;;
      --name) INSTALL_NAME="$2"; shift 2 ;;
      --from-source) BUILD_FROM_SOURCE=1; shift ;;
      -h|--help)
        sed -n '2,12p' "$0"
        exit 0 ;;
      *) err "unknown flag: $1"; exit 1 ;;
    esac
  done
  detect
  if [ "$BUILD_FROM_SOURCE" = "1" ]; then
    install_source
  else
    install_release || { info "no prebuilt asset, building from source"; install_source; }
  fi
  info "next: run '${INSTALL_NAME} config --api-key sk-xxx' then '${INSTALL_NAME} start'"
  info "ensure ${INSTALL_DIR} is on your PATH"
}

main "$@"