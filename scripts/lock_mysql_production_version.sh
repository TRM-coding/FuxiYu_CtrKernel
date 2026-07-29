#!/usr/bin/env bash
set -euo pipefail

# Lock the MySQL production package set to the versions currently verified on
# this host. Run with sudo after confirming the running MySQL version is healthy.

MYSQL_VERSION="8.0.46-0ubuntu0.24.04.2"
MYSQL_COMMON_VERSION="5.8+1.1.0build1"
PIN_FILE="/etc/apt/preferences.d/mysql-production-lock"

MYSQL_PACKAGES=(
  mysql-client-8.0
  mysql-client-core-8.0
  mysql-server
  mysql-server-8.0
  mysql-server-core-8.0
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo $0" >&2
  exit 1
fi

cat > "${PIN_FILE}" <<EOF
Package: mysql-client-8.0 mysql-client-core-8.0 mysql-server mysql-server-8.0 mysql-server-core-8.0
Pin: version ${MYSQL_VERSION}
Pin-Priority: 1001

Package: mysql-common
Pin: version ${MYSQL_COMMON_VERSION}
Pin-Priority: 1001
EOF

apt-mark hold "${MYSQL_PACKAGES[@]}" mysql-common

echo "MySQL production packages are locked:"
dpkg-query -W -f='${binary:Package}\t${Version}\t${db:Status-Abbrev}\n' \
  "${MYSQL_PACKAGES[@]}" mysql-common | sort

echo
echo "Pin file written to ${PIN_FILE}"
echo "Held packages:"
apt-mark showhold | grep -E '^(mysql-client-8.0|mysql-client-core-8.0|mysql-common|mysql-server|mysql-server-8.0|mysql-server-core-8.0)$' | sort
