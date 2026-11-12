#!/bin/bash
set -e

sudo nft add table inet cerberus

sudo nft 'add set inet cerberus blackhole { type ipv4_addr; flags timeout; }'

sudo nft 'add chain inet cerberus input { type filter hook input priority 0; policy accept; }'

sudo nft flush chain inet cerberus input

sudo nft add rule inet cerberus input ip saddr @blackhole counter drop

echo "Cerberus nftables firewall ruleset initialized successfully."
