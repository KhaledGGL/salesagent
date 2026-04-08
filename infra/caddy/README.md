# Caddy reverse proxy — multi-agent VPS layout

This directory holds a standalone Caddy reverse proxy that fronts every
agent running on the same VPS, with **path-based routing under a single
hostname** (`api.<DOMAIN>`).

## What it solves

- **One hostname for everything.** Instead of `salesgrader.example.com`,
  `sdr.example.com`, etc., everything lives at `api.example.com/<agent>`.
- **One TLS cert** managed automatically by Let's Encrypt.
- **Backend isolation.** Each agent stays in its own Docker Compose
  project on its own private network. Caddy is the only thing that can
  reach the agents publicly.
- **Easy to add agents.** New agent → new `handle_path` block in the
  `Caddyfile` → `docker compose restart caddy`.

## Layout

The recommended layout on the VPS:

```
/srv/
├── caddy/                    ← this directory (reverse proxy + TLS)
│   ├── docker-compose.yml
│   ├── Caddyfile
│   └── .env
├── salesagent/               ← agent #1: sales call analyzer
│   ├── docker-compose.yml
│   └── .env
├── sdr-agent/                ← agent #2 (future)
│   └── ...
└── sheets-agent/             ← agent #3 (future)
    └── ...
```

Each agent is a separate Compose project. They communicate with Caddy
through a **shared external Docker network** named `web`.

## One-time host setup

Run these on the VPS once, before bringing up Caddy or any agent:

```bash
# 1. Install Docker + Docker Compose v2 (skip if already done)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER     # log out + back in for this to take effect

# 2. Create the shared network that Caddy and all agents will join
docker network create web

# 3. Open ports 80 and 443 in the firewall (UFW example)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## DNS

Point an A record at the VPS:

```
api.yourdomain.com   A   <vps-public-ipv4>
```

(Optional but recommended: also add a AAAA record for IPv6.)

Wait for DNS propagation (usually a few minutes; check with
`dig api.yourdomain.com`) before bringing up Caddy, otherwise the
Let's Encrypt HTTP-01 challenge will fail.

## Bringing up Caddy

```bash
cd /srv/caddy
cp .env.example .env
nano .env                          # fill in DOMAIN and ACME_EMAIL
docker compose up -d
docker compose logs -f caddy       # watch the cert issuance
```

You should see lines like:
```
obtaining certificate for api.yourdomain.com
certificate obtained successfully
```

After that, `https://api.yourdomain.com/` will return:
```
Caddy reverse proxy OK. Use /<agent>/<path> to reach a service.
```

## Hooking up an agent

Each agent's `docker-compose.yml` needs two changes to be reachable
from Caddy:

1. **Declare the `web` network as external** at the bottom of the file:
   ```yaml
   networks:
     web:
       external: true
   ```

2. **Attach the public-facing service** (typically the API container)
   to BOTH its own private network AND `web`:
   ```yaml
   services:
     api:
       # ... existing config ...
       networks:
         - default     # private to this agent's project (auto-created)
         - web         # shared with Caddy
   ```

   Worker / beat / Redis / Postgres containers should stay on `default`
   only — they don't need to be reachable from outside their own project.

3. **Add a `handle_path` block** in `infra/caddy/Caddyfile` pointing at
   the agent's container name + internal port:
   ```caddyfile
   handle_path /your-agent/* {
       reverse_proxy your_agent_api:8000 {
           header_up X-Real-IP {remote_host}
           header_up X-Forwarded-For {remote_host}
           header_up X-Forwarded-Proto {scheme}
       }
   }
   ```

4. **Reload Caddy:**
   ```bash
   cd /srv/caddy
   docker compose restart caddy
   ```

5. **Test:**
   ```bash
   curl https://api.yourdomain.com/your-agent/health
   ```

## Sales Call Analyzer (already wired up)

The salesagent project's `docker-compose.yml` is already updated to join
the `web` network. After the host setup above, just bring it up normally:

```bash
cd /srv/salesagent
docker compose up -d
```

The webhook URL to give to GoHighLevel becomes:

```
https://api.yourdomain.com/salesgrader/webhooks/ghl/transcript-ready
```

Health check from anywhere:
```bash
curl https://api.yourdomain.com/salesgrader/health/ready
```

## Container naming and conflicts

Each agent's compose file should use a **unique container name prefix**
so that running multiple agents on the same host doesn't collide:

| Agent | Container name pattern |
|---|---|
| salesagent | `sales_api`, `sales_worker`, `sales_redis`, ... |
| sdr-agent | `sdr_api`, `sdr_worker`, ... |
| sheets-agent | `sheets_api`, `sheets_worker`, ... |

If you copy `docker-compose.yml` from one agent to start another, **change
the `container_name` values first** or remove the `container_name:` lines
entirely (Docker will auto-name as `<project>-<service>-1`).

## Operations

### View Caddy logs
```bash
cd /srv/caddy
docker compose logs -f --tail=50 caddy
```

### Reload Caddy after Caddyfile changes
```bash
docker compose restart caddy
```

(Caddy supports a hot reload via `caddy reload` inside the container,
but a restart is simpler and only takes ~1 second.)

### Renew certificates
Caddy renews automatically. No action required.

### Backup the cert volume
```bash
docker run --rm -v caddy_data:/data -v $PWD:/backup alpine \
  tar czf /backup/caddy_data_$(date +%F).tgz -C /data .
```

Losing the `caddy_data` volume means re-issuing all certs from
Let's Encrypt, which is fine but counts against rate limits.

### Adding HTTP basic auth (e.g. for Flower)
```caddyfile
handle_path /salesgrader/flower/* {
    basicauth {
        admin <bcrypt-hash-of-password>
    }
    reverse_proxy sales_flower:5555
}
```

Generate the bcrypt hash:
```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext "yourpassword"
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `502 Bad Gateway` from Caddy | Backend container is down OR not on the `web` network | `docker network inspect web` to confirm the agent's API container is attached |
| Cert issuance fails with `connection refused` on port 80 | Firewall blocks port 80 | `sudo ufw allow 80/tcp` |
| Cert issuance fails with `DNS problem: NXDOMAIN` | DNS A record not propagated yet | `dig api.yourdomain.com` and wait |
| `Caddyfile invalid` on startup | Syntax error | `docker compose run --rm caddy caddy validate --config /etc/caddy/Caddyfile` |
| Hit rate limit on Let's Encrypt | Too many cert requests during testing | Uncomment the `acme_ca` staging line in the Caddyfile and use the staging environment until you're confident |
| Caddy works on apex but not subpath | `handle` vs `handle_path` confusion | Use `handle_path` (with the `_path`) — it strips the prefix before forwarding. `handle` does NOT strip. |
