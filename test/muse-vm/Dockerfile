# Local stand-in for a Muse agent VM -- see run.sh. Mirrors what we know of the
# real ones: Ubuntu 24.04, system-level systemd (no user bus), home at
# /home/hatch, the sandbox API socket, and the outbound tunnel proxy on :3130.
FROM ubuntu:24.04

RUN apt-get update \
 && apt-get install -y --no-install-recommends systemd systemd-sysv python3 procps iproute2 curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -d /home/hatch hatch \
 && mkdir -p /home/hatch/workspace/notes /home/hatch/workspace/slack-watch /home/hatch/memory \
 && echo '{"last_ts": "0"}' > /home/hatch/workspace/slack-watch/seen.json \
 && echo '# Notes' > /home/hatch/workspace/notes/plan.md \
 && echo '[]' > /home/hatch/feed.json

COPY fake_sandbox_api.py tunnel_proxy.py /opt/muse/

RUN printf '[Unit]\nDescription=Fake Muse sandbox API (activity feed socket)\n[Service]\nExecStart=/usr/bin/python3 /opt/muse/fake_sandbox_api.py\nRuntimeDirectory=hatch/sandbox-api\nRestart=always\n[Install]\nWantedBy=multi-user.target\n' > /etc/systemd/system/muse-sandbox-api.service \
 && printf '[Unit]\nDescription=Fake Muse tunnel proxy (:3130)\n[Service]\nExecStart=/usr/bin/python3 /opt/muse/tunnel_proxy.py\nRestart=always\n[Install]\nWantedBy=multi-user.target\n' > /etc/systemd/system/muse-tunnel-proxy.service \
 && systemctl enable muse-sandbox-api muse-tunnel-proxy

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
