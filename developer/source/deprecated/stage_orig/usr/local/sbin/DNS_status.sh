#!/usr/bin/env bash
set -euo pipefail
echo "== DNS status =="
systemctl --no-pager --full status DNS-redirect unbound@US unbound@x6 || true
echo
echo "== nftables =="
nft list table inet NAT-DNS-REDIRECT || true
echo
echo "== Unbound logs (last 50 lines each) =="
journalctl -u unbound@US -n 50 --no-pager || true
echo
journalctl -u unbound@x6 -n 50 --no-pager || true
