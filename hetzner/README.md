# Buzz relay on Hetzner (tailnet-only)

This directory is the only fork-specific part of this repository. Everything
else tracks upstream `block/buzz` unchanged, so `bin/sync-fork` can rebase the
fork onto upstream without conflicts. Keep it that way: never edit files
outside `hetzner/` (future fork workflows go in `.github/workflows/fork-*.yml`).

## What runs where

| Piece | Where |
| --- | --- |
| Relay, Postgres, Redis, Silo object store | Docker Compose on one Hetzner server, project `buzz-prod` |
| Compose files | Upstream `deploy/compose/compose.yml` at the pinned commit, plus `compose/compose.override.yml` |
| Ingress | Tailscale Serve, `https://<tailnet name>` → `127.0.0.1:3000`. No public TCP ports. |
| Admin access | Tailscale SSH (tailnet policy decides who). Hetzner rescue + `admin.sshPrivateKey` is break-glass. |
| Config and secrets | Pulumi ESC environment `EwanDawson/buzz-relay/prod` |
| Infrastructure | Pulumi stack `EwanDawson/buzz-relay/prod` (`infra/`) |
| Backups | restic over SFTP to a Hetzner Storage Box (only reachable from Hetzner's network), nightly at 03:00 UTC |

## Files

| Path | Purpose |
| --- | --- |
| `versions.lock` | Upstream commit and every image digest. The only thing an upgrade changes. |
| `compose/compose.override.yml` | Pins images from `versions.lock`, tunes Postgres for 4 GB, bounds logs |
| `infra/` | Pulumi YAML: server, firewall, Tailscale bootstrap key, Storage Box |
| `host/buzzctl` | Canonical wrapper on the server (installed to `/usr/local/sbin/buzzctl`) |
| `host/systemd/` | Timers: health every minute, backup nightly, restore drill monthly |
| `bin/` | Operator-side scripts: `render-env`, `push-env`, `deploy`, `bump`, `sync-fork` |

## Server layout

| Path | Contents |
| --- | --- |
| `/opt/buzz` | Clone of this fork, checked out at the deployed ref |
| `/etc/buzz/buzz.env` | Relay and Compose env (root, 0600), rendered from ESC |
| `/etc/buzz/backup.env`, `/etc/buzz/ssh/storagebox` | restic repository, password, Storage Box key (root, 0600) |
| `/var/lib/buzz/bundle/<commit>/` | Upstream `deploy/compose` at that commit; `.env` links to `/etc/buzz/buzz.env` |
| `/var/lib/buzz/deployed.lock` | `versions.lock` that is currently running |
| `/var/lib/buzz/status.json` | Latest health snapshot (`buzzctl health`) |

Volumes: `buzz-prod_buzz-postgres-data`, `buzz-prod_buzz-redis-data`,
`buzz-prod_buzz-minio-data`, `buzz-prod_buzz-git-data`. Never prune them.

## Runbooks

All operator commands assume a machine on the tailnet that is logged in to
Pulumi. `bin/*` reach the server with `ssh` over `tailscale nc`.

### First provisioning

1. ESC holds the Hetzner token, Tailscale OAuth client, owner pubkey and generated secrets.
2. `cd hetzner/infra && pulumi up -s EwanDawson/buzz-relay/prod` creates the
   server (protected against delete and rebuild), firewall, bootstrap key and Storage Box.
3. Wait for `/var/lib/buzz/cloud-init-done` on the server, then record the
   server's tailnet name in ESC: `pulumi env set EwanDawson/buzz-relay/prod tailscale.fqdn buzz.<tailnet>.ts.net`.
4. `bin/deploy main`, then on the server `buzzctl backup-init && buzzctl backup && buzzctl restore-drill`.

### Day to day

```
bin/deploy [ref]            # push env from ESC, check out ref, buzzctl install + deploy
ssh … buzzctl status        # compose ps
ssh … buzzctl health        # JSON snapshot; exit 1 when unhealthy
ssh … buzzctl logs [svc]
ssh … buzzctl compose …     # any compose command with the canonical project and files
```

### Upgrade (weekly)

1. `bin/sync-fork` rebases the fork's `main` onto upstream and force-pushes it.
   It lists upstream workflows; disable any new ones in the fork's Actions settings.
2. `bin/bump` points `versions.lock` at the newest upstream `main` commit with a
   published image and re-pins every digest. Open a PR with the changelog.
3. After the PR merges, `bin/deploy main`. `buzzctl deploy` then:
   takes a pre-upgrade backup (aborts if it fails), pulls, runs
   `buzz-admin migrate`, starts the relay, smoke-tests it, and on failure puts
   the previous relay image back. Migrations are forward-only and stay applied;
   restoring data is a separate, approved step.

### Backups and restore

- Nightly `buzzctl backup`: `pg_dump -Fc`, Redis AOF rewrite, then restic of the
  dump, the env file, `versions.lock`, and the Silo, Git and Redis volumes.
  Sundays also apply retention (7 daily, 5 weekly, 6 monthly). No downtime.
- Monthly `buzzctl restore-drill`: restores the latest snapshot to scratch
  space, loads the dump into a throwaway Postgres with no network, counts
  events, objects and Git files. Production is never touched.
- A live restore (stop relay, restore volumes and `pg_restore` into production)
  discards newer writes and needs the owner's explicit approval each time.

### Disk, memory and size

`buzzctl health` flags disk above 80%, available memory below 20%, a backup
older than 26 hours, or any unhealthy container. Resize with Pulumi
(`serverType`), never by splitting services onto other hosts.

## Limits

One server. A Hetzner outage or a lost server means restoring from the Storage
Box onto a new server; recent writes since the last backup are lost. Nothing is
reachable from the public internet.
