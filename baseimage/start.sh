#!/bin/bash
set -e
# enable IP forwarding (container expected to run privileged)
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

# start daemons
# start sshd so we can SSH into containers for provisioning
/usr/sbin/sshd || true

# ensure root has a known password for lab provisioning (only for test environments)
echo 'root:root' | chpasswd || true

if [ "${ENABLE_OVS:-0}" = "1" ]; then
	/usr/share/openvswitch/scripts/ovs-ctl start || true
	ovs-vsctl --may-exist add-br br0 || true
	ovs-vsctl set-fail-mode br0 secure || true
	ovs-vsctl --may-exist set-controller br0 "tcp:${RYU_CONTROLLER:-127.0.0.1}:6633" || true
	ovs-vsctl set bridge br0 protocols=OpenFlow13 || true
fi

zebra -d -f /etc/quagga/zebra.conf
ospfd -d -f /etc/quagga/ospfd.conf

if [ -f /etc/quagga/bgpd.conf ]; then
	bgpd -d -f /etc/quagga/bgpd.conf
fi

exec /root/sleep.sh
