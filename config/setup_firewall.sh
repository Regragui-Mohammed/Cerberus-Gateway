#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# 1. Install cerberus-ban wrapper if present in repo
if [ -f "$REPO_ROOT/scripts/cerberus-ban" ]; then
    echo "Installing cerberus-ban wrapper to /usr/local/bin/..."
    sudo cp "$REPO_ROOT/scripts/cerberus-ban" /usr/local/bin/cerberus-ban
    sudo chmod 755 /usr/local/bin/cerberus-ban
fi

# 2. Configure nftables ruleset
sudo nft add table inet cerberus
sudo nft 'add set inet cerberus blackhole { type ipv4_addr; flags timeout; }'
sudo nft 'add chain inet cerberus input { type filter hook input priority 0; policy accept; }'
sudo nft flush chain inet cerberus input
sudo nft add rule inet cerberus input ip saddr @blackhole counter drop

echo "Cerberus nftables firewall ruleset initialized successfully."
