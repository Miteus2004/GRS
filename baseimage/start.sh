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
	timeout 5s /usr/share/openvswitch/scripts/ovs-ctl start || true
	ovs-vswitchd unix:/var/run/openvswitch/db.sock --pidfile --detach --log-file=/var/log/openvswitch/ovs-vswitchd.log || true
	timeout 5s ovs-vsctl --may-exist add-br br0 || true
	timeout 5s ovs-vsctl set-fail-mode br0 secure || true
	for _ in 1 2 3 4 5; do
		timeout 5s ovs-vsctl set-controller br0 "tcp:${RYU_CONTROLLER:-127.0.0.1}:6633" && break || true
		sleep 1
	done
	timeout 5s ovs-vsctl set bridge br0 protocols=OpenFlow13 || true
fi

if [ -f /etc/quagga/zebra.conf ]; then
	zebra -d -f /etc/quagga/zebra.conf
fi

if [ -f /etc/quagga/ospfd.conf ]; then
	ospfd -d -f /etc/quagga/ospfd.conf
fi

if [ -f /etc/quagga/bgpd.conf ]; then
	bgpd -d -f /etc/quagga/bgpd.conf
fi

exec /root/sleep.sh
