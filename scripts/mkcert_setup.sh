#!/usr/bin/env bash
# Helper to generate locally-trusted certs using mkcert
# Enhancements:
# - detect missing mkcert and offer to install it (requires sudo)
# - install libnss3-tools on Debian/Ubuntu if needed for Firefox
# - download mkcert binary from GitHub releases when package manager not available

set -euo pipefail

BASEDIR=$(cd "$(dirname "$0")/.." && pwd)
CERT_DIR="$BASEDIR/certs"

mkdir -p "$CERT_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

detect_pkg_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  elif command -v pacman >/dev/null 2>&1; then
    echo "pacman"
  else
    echo "none"
  fi
}

arch_map() {
  case "$(uname -m)" in
    x86_64) echo "linux-amd64" ;;
    aarch64|arm64) echo "linux-arm64" ;;
    *) echo "" ;;
  esac
}

install_mkcert_via_pkg() {
  pm="$1"
  case "$pm" in
    apt)
      sudo apt-get update
      sudo apt-get install -y libnss3-tools
      # apt may not package mkcert; try to install via snap or download below
      if command -v snap >/dev/null 2>&1; then
        if sudo snap install mkcert; then
          return 0
        else
          echo "snap install mkcert failed; will try GitHub binary fallback instead." >&2
          return 1
        fi
      fi
      return 1
      ;;
    dnf|yum)
      sudo "$pm" install -y nss-tools
      return 1
      ;;
    pacman)
      sudo pacman -S --noconfirm nss
      return 1
      ;;
    *) return 1 ;;
  esac
}

install_mkcert_from_github() {
  echo "Attempting to download mkcert binary from GitHub releases..."
  arch_tag=$(arch_map)
  if [ -z "$arch_tag" ]; then
    echo "Unsupported architecture: $(uname -m)" >&2
    return 1
  fi

  api_url="https://api.github.com/repos/FiloSottile/mkcert/releases/latest"
  download_url=$(curl -s "$api_url" | grep -E "browser_download_url.*$arch_tag" | head -n1 | cut -d '"' -f4)
  if [ -z "$download_url" ]; then
    echo "Could not find a suitable mkcert binary in releases." >&2
    return 1
  fi

  tmpfile=$(mktemp)
  echo "Downloading: $download_url"
  curl -sL "$download_url" -o "$tmpfile"
  chmod +x "$tmpfile"

  echo "Installing mkcert to /usr/local/bin (requires sudo)"
  sudo mv "$tmpfile" /usr/local/bin/mkcert
  sudo chmod +x /usr/local/bin/mkcert
  echo "mkcert installed to /usr/local/bin/mkcert"
  return 0
}

ensure_mkcert() {
  if command -v mkcert >/dev/null 2>&1; then
    return 0
  fi

  echo "mkcert not found on PATH."
  read -p "Try to install mkcert locally? This may use sudo. [y/N]: " ans
  case "$ans" in
    y|Y)
      pm=$(detect_pkg_manager)
      if [ "$pm" != "none" ]; then
        if install_mkcert_via_pkg "$pm"; then
          return 0
        fi
      fi
      if install_mkcert_from_github; then
        return 0
      fi
      echo "Automatic installation failed; please install mkcert manually: https://github.com/FiloSottile/mkcert#installation" >&2
      return 1
      ;;
    *)
      echo "Aborting; please install mkcert and re-run this script." >&2
      return 1
      ;;
  esac
}

echo "Ensuring mkcert is available..."
if ! ensure_mkcert; then
  fail "mkcert is required to generate trusted certs."
fi

echo "Ensuring libnss3-tools (for Firefox trust) is present when possible..."
pm=$(detect_pkg_manager)
if [ "$pm" = "apt" ]; then
  if ! dpkg -s libnss3-tools >/dev/null 2>&1; then
    echo "Installing libnss3-tools via apt (requires sudo)..."
    sudo apt-get update
    sudo apt-get install -y libnss3-tools || true
  fi
fi

echo "Installing local CA (if needed)..."
mkcert -install

# Determine extra hosts to include in the certificate SANs.
# Priority: command-line args > detect first non-loopback IPv4 > none
EXTRA_HOSTS=()
if [ "$#" -gt 0 ]; then
  # take all args as hosts
  for a in "$@"; do
    EXTRA_HOSTS+=("$a")
  done
else
  # try to detect the first non-loopback IPv4 address
  if command -v ip >/dev/null 2>&1; then
    detected_ip=$(ip -4 addr show scope global | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1 || true)
  else
    detected_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
  fi
  if [ -n "$detected_ip" ]; then
    EXTRA_HOSTS+=("$detected_ip")
  fi
fi

SAN_LIST=(localhost 127.0.0.1 ::1)
for h in "${EXTRA_HOSTS[@]}"; do
  SAN_LIST+=("$h")
done

echo "Generating certificate for: ${SAN_LIST[*]}"
# name the files according to first SAN (localhost) for backwards-compatibility
mkcert -cert-file "$CERT_DIR/localhost.pem" -key-file "$CERT_DIR/localhost-key.pem" "${SAN_LIST[@]}"

echo "Certificates written to: $CERT_DIR"
echo
echo "To enable HTTPS in dev, set ENABLE_SSL=true and run run.py."
echo "Example: ENABLE_SSL=true python -m FuxiYu_CtrKernel.run"

exit 0
