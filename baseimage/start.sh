#!/bin/bash
set -e

zebra -d -f /etc/quagga/zebra.conf
ospfd -d -f /etc/quagga/ospfd.conf

if [ -f /etc/quagga/bgpd.conf ]; then
	bgpd -d -f /etc/quagga/bgpd.conf
fi

exec /root/sleep.sh
