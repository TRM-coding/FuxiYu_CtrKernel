#!/usr/bin/env bash
# Copy generated mkcert certs from backend project to front-end certs directory
# Usage: bash scripts/copy_certs_to_frontend.sh [optional-source-dir]
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BACKEND_CERT_DIR="$ROOT_DIR/certs"
FRONTEND_DIR="$ROOT_DIR/../FuxiYu_Web/certs"

if [ "$#" -gt 0 ]; then
  BACKEND_CERT_DIR="$1"
fi

mkdir -p "$FRONTEND_DIR"

echo "Copying certs from $BACKEND_CERT_DIR to $FRONTEND_DIR"
if [ -f "$BACKEND_CERT_DIR/localhost.pem" ] && [ -f "$BACKEND_CERT_DIR/localhost-key.pem" ]; then
  cp -f "$BACKEND_CERT_DIR/localhost.pem" "$FRONTEND_DIR/localhost.pem"
  cp -f "$BACKEND_CERT_DIR/localhost-key.pem" "$FRONTEND_DIR/localhost-key.pem"
  chmod 644 "$FRONTEND_DIR/localhost.pem" || true
  chmod 600 "$FRONTEND_DIR/localhost-key.pem" || true
  echo "Copied to $FRONTEND_DIR"
else
  echo "Cert files not found in $BACKEND_CERT_DIR. Run mkcert_setup.sh first." >&2
  exit 1
fi

exit 0
