# NeCTAR Hosting VM Setup Guide

Concrete steps for standing up a hosting VM on NeCTAR OpenStack (ace-eco-stats
allocation) with nginx reverse proxy, HTTPS, and systemd services. Distilled
from an actual setup session on 2026-04-03.

## VM provisioning

Launch Ubuntu 24.04 on NeCTAR. Name the instance (e.g. `aad`). Minimum spec
for lonboard + plumber2: 2 vCPU, 4 GB RAM.

Security group — open inbound TCP: 22, 80, 443.

## DNS

DNS is **not automatic** on NeCTAR. You must create the A record manually.
The zone is `ace-eco-stats.cloud.edu.au.` and records are flat under it
(`{machine}.ace-eco-stats.cloud.edu.au`).

```bash
# Source your application credential
source app-cred-*-openrc.sh

# Install CLI (once)
pip install python-openstackclient python-designateclient --break-system-packages

# Check existing records
openstack recordset list ace-eco-stats.cloud.edu.au.

# Create yours (trailing dot on zone name required)
openstack recordset create ace-eco-stats.cloud.edu.au. \
  aad --type A --record <YOUR_IP>
```

**Negative caching gotcha:** if you `dig` before the record exists, the
resolver caches the NXDOMAIN for up to 30 minutes (the SOA negative TTL).
To check whether the record is actually live, query the authoritative server
directly:

```bash
dig aad.ace-eco-stats.cloud.edu.au @ns1.rc.nectar.org.au
```

Once the local resolver catches up, `dig aad.ace-eco-stats.cloud.edu.au`
will return the A record.

## Base packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx certbot python3-certbot-nginx ufw git curl
```

## Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

## Python environment (uv + venv)

Don't `sudo uv` — it installs Python under root's cache. Create the
directory with correct ownership, then run uv as your user.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Create venv (Python 3.12 — possibly safer for current lonboard compatibility)
uv python install 3.12
sudo mkdir -p /opt/lonboard-env
sudo chown ubuntu:ubuntu /opt/lonboard-env
uv venv --python 3.12 /opt/lonboard-env

# Install deps
source /opt/lonboard-env/bin/activate
uv pip install \
  lonboard \
  shiny \
  shinywidgets \
  async-geotiff \
  obstore \
  pillow \
  numpy \
  matplotlib \
  morecantile \
  uvicorn
deactivate
```

**Note on Python version:** 3.14 is current stable and has excellent wheel
coverage, but lonboard 0.16.0 (released 2026-04-02) introduced breaking API
changes.

## Deploy the app

```bash
sudo mkdir -p /opt/apps/lonboard
# scp or git clone your app.py here
```

## systemd service

```bash
sudo tee /etc/systemd/system/lonboard.service << 'EOF'
[Unit]
Description=Lonboard Python Shiny App
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/apps/lonboard
Environment="PATH=/opt/lonboard-env/bin:/usr/local/bin:/usr/bin"
ExecStart=/opt/lonboard-env/bin/shiny run app.py \
  --host 127.0.0.1 --port 8765
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now lonboard
```

## nginx

The `map $http_upgrade` block must be at the `http {}` level in
`/etc/nginx/nginx.conf`, not inside a server block. Add it there if not
already present:

```nginx
# In /etc/nginx/nginx.conf, inside http { }
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

Then create the site config:

```bash
sudo tee /etc/nginx/sites-available/hosting << 'NGINX'
server {
    listen 80;
    server_name aad.ace-eco-stats.cloud.edu.au;

    location /lonboard/ {
        rewrite ^/lonboard/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8765;
        proxy_redirect / /lonboard/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 20d;
        proxy_buffering off;
    }

    location / {
        return 200 'hosting server is up\n';
        add_header Content-Type text/plain;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/hosting /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

**WebSocket proxying** is essential for Shiny — the `Upgrade` and
`Connection` headers plus `proxy_http_version 1.1` are what make it work.
Without these, the app serves HTML but never becomes interactive.

## HTTPS (Let's Encrypt)

Wait for DNS to propagate (check with `dig`), then:

```bash
sudo certbot --nginx -d aad.ace-eco-stats.cloud.edu.au
```

Certbot modifies the nginx config automatically — adds `listen 443 ssl`,
cert paths, and HTTP→HTTPS redirect. Auto-renewal is configured via systemd
timer.

Keep port 80 open — certbot renewal uses HTTP-01 challenges on port 80, and
the redirect ensures all user traffic goes to HTTPS.

## Debugging checklist

```bash
# Is the app running?
sudo systemctl status lonboard
sudo journalctl -u lonboard -e

# Does the backend respond?
curl http://127.0.0.1:8765/

# Does nginx route correctly?
curl -H "Host: aad.ace-eco-stats.cloud.edu.au" http://127.0.0.1/lonboard/

# Is nginx config valid?
sudo nginx -t

# Does DNS resolve?
dig aad.ace-eco-stats.cloud.edu.au
dig aad.ace-eco-stats.cloud.edu.au @ns1.rc.nectar.org.au  # bypass cache
```

## Updating the app

```bash
# From local machine
scp app.py ubuntu@aad.ace-eco-stats.cloud.edu.au:/opt/apps/lonboard/
ssh ubuntu@aad.ace-eco-stats.cloud.edu.au sudo systemctl restart lonboard

# Or edit on the VM directly
nano /opt/apps/lonboard/app.py
sudo systemctl restart lonboard
```

## Adding more services

Each new service (e.g. plumber2 tiles on `/tiles/`) needs:

1. A systemd unit file (copy and adapt, different port)
2. An nginx `location` block in the same site config
3. `sudo systemctl daemon-reload && sudo systemctl enable --now myservice`
4. `sudo nginx -t && sudo systemctl reload nginx`

Port assignments:

| Service        | Port | Path      |
|----------------|------|-----------|
| lonboard       | 8765 | /lonboard |
| plumber2 tiles | 8000 | /tiles    |

## Lessons learned

- **Don't `sudo uv`** — creates Python installs under root. Use `sudo mkdir`
  + `sudo chown` to create the venv directory, then run uv as your user.
- **DNS is manual on NeCTAR** — use `openstack recordset create`. The zone
  is `ace-eco-stats.cloud.edu.au.` with flat `{name}.ace-eco-stats...` records.
- **Negative DNS caching** — if you dig before the record exists, you'll wait
  up to 30 minutes. Use `dig @ns1.rc.nectar.org.au` to check the source.
- **Pin package versions on hosting boxes** — lonboard 0.16.0 dropped the day
  we deployed. 
- **WebSocket proxy headers are non-negotiable** — `Upgrade`, `Connection`,
  and `proxy_http_version 1.1` in the nginx location block. Without them,
  Shiny apps serve static HTML but never connect.
- **Keep port 80 open** — certbot renewal needs it, and nginx redirects to
  HTTPS automatically.
