FROM netubuntu:latest
RUN apt-get update && apt-get install -y bind9 bind9utils && rm -rf /var/lib/apt/lists/*
CMD ["/usr/sbin/named", "-g", "-u", "bind"]
