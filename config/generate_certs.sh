#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS_DIR="$SCRIPT_DIR/certs"
mkdir -p "$CERTS_DIR"
cd "$CERTS_DIR"

# 1. Certificate Authority (CA) with strict X.509 v3 CA extensions
openssl req -new -x509 -days 365 -nodes -out ca.pem -keyout ca.key -subj "/CN=Cerberus_CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"

# 2. Server Certificate with SAN and serverAuth
openssl req -new -nodes -out server.csr -keyout server.key -subj "/CN=Cerberus_Server" \
    -addext "subjectAltName=DNS:localhost,DNS:Cerberus_Server,IP:127.0.0.1" \
    -addext "extendedKeyUsage=serverAuth"
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out server.pem -days 365 -copy_extensions copy

# 3. Client Certificate (Tenant_001) with clientAuth
openssl req -new -nodes -out client.csr -keyout client.key -subj "/CN=Tenant_001" \
    -addext "extendedKeyUsage=clientAuth"
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out client.pem -days 365 -copy_extensions copy

# Provide client1 alias for backwards compatibility
cp -f client.pem client1.pem
cp -f client.key client1.key

echo "mTLS Certificates Are Ready in: $CERTS_DIR"
