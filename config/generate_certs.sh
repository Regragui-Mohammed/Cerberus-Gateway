#!/bin/bash
cd config
mkdir -p certs 
cd certs

openssl req -new -x509 -day 365 -nodes -out ca.pem -keyout ca.key -subj "/CN=Cerberus_CA"

openssl req -new -nodes -out server.csr -keyout server.key -subj "/CN=Cerberus_Server"
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out server.pem -days 365

openssl req -new -nodes -out client1.csr -keyout client1.key -subj "/CN=Tenant_001"
openssl x509 -req -in client1.csr -CA ca.pem -CAkey ca.key -CAcreateserial -out client1.pem -days 365

echo "mTLS Certificates Are Ready in the config/certs/ folder"
