FROM ubuntu:20.04
RUN apt update && apt install -y vim iproute2 iputils-ping tcpdump iptables dnsutils curl
RUN apt update && apt install -y quagga
RUN apt update && apt install -y openvswitch-switch
RUN apt update && apt install -y openssh-server
RUN mkdir -p /var/run/sshd
RUN sed -i 's/^#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config || true
RUN sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config || true
# Set root password to 'root' for testing (keep only for lab/test environments)
RUN echo 'root:root' | chpasswd
RUN apt update && apt install -y telnet
RUN mkdir -p /var/log/quagga
RUN chown quagga:quagga /var/log/quagga
RUN mkdir /run/quagga
RUN chmod a+w /run/quagga
COPY sleep.sh /root/sleep.sh
COPY start.sh /root/start.sh
ENTRYPOINT ["/root/start.sh"]