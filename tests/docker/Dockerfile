FROM python:3.11-slim-bookworm
ENV container=docker DEBIAN_FRONTEND=noninteractive
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && apt-get update -qq && apt-get install -y -qq --no-install-recommends systemd systemd-sysv openssh-server curl openssl ca-certificates iproute2 qrencode caddy sudo gnupg debian-keyring debian-archive-keyring apt-transport-https && rm -rf /var/lib/apt/lists/* && mkdir -p /run/sshd && ssh-keygen -A && printf '\nPermitRootLogin yes\nPasswordAuthentication yes\n' >> /etc/ssh/sshd_config && systemctl enable ssh && systemctl disable caddy && rm -f /etc/caddy/Caddyfile
ARG TARGETARCH
COPY packages/caddy_2.10.2_linux_${TARGETARCH}.tar.gz /tmp/caddy.tgz
RUN case "$(uname -m)" in \
    aarch64) echo "6ce061a690312ab38367df3c5d5f89a2e4a263e7300d300d87356211bb81e79b15933e6d6203e03fbf26f15cc0311f264805f336147dbdd24938d84b57a4421c  /tmp/caddy.tgz" | sha512sum -c - ;; \
    x86_64) echo "747df7ee74de188485157a383633a1a963fd9233b71fbb4a69ddcbcc589ce4e2cc82dacf5dbbe136cb51d17e14c59daeb5d9bc92487610b0f3b93680b2646546  /tmp/caddy.tgz" | sha512sum -c - ;; \
    *) exit 1 ;; esac \
 && tar xzf /tmp/caddy.tgz -C /usr/bin caddy && rm /tmp/caddy.tgz
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
