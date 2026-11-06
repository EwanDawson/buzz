"""Turn the opened ESC environment (JSON on stdin) into host files.

Writes buzz.env, backup.env, storagebox (private key) and storagebox.conf
(ssh client config) into the target directory, all mode 0600.
"""
import json
import os
import sys

out, sb_user, sb_host = sys.argv[1], sys.argv[2], sys.argv[3]
env = json.load(sys.stdin)
buzz = env["buzz"]
domain = env["tailscale"].get("fqdn")
owner = buzz.get("ownerPubkey")
missing = [k for k, v in {"tailscale.fqdn": domain, "buzz.ownerPubkey": owner}.items() if not v]
if missing:
    sys.exit("missing ESC values: " + ", ".join(missing))
if len(owner) != 64 or any(c not in "0123456789abcdef" for c in owner):
    sys.exit("buzz.ownerPubkey must be 64 lowercase hex characters")

relay_env = {
    "BUZZ_DOMAIN": domain,
    "RELAY_URL": f"wss://{domain}",
    "BUZZ_MEDIA_BASE_URL": f"https://{domain}/media",
    "BUZZ_MEDIA_SERVER_DOMAIN": domain,
    "BUZZ_CORS_ORIGINS": f"https://{domain}",
    "BUZZ_REQUIRE_AUTH_TOKEN": "true",
    "BUZZ_REQUIRE_RELAY_MEMBERSHIP": "true",
    "BUZZ_ALLOW_NIP_OA_AUTH": "true",
    "BUZZ_AUTO_MIGRATE": "false",
    "BUZZ_GIT_CONFORMANCE_PROBE": "true",
    "BUZZ_PUSH_ENABLED": "false",
    "RUST_LOG": "buzz_relay=info,buzz_db=info,buzz_auth=info,buzz_pubsub=info,tower_http=info",
    "RELAY_OWNER_PUBKEY": owner,
    "BUZZ_RELAY_PRIVATE_KEY": buzz["relay"]["privateKey"],
    "BUZZ_GIT_HOOK_HMAC_SECRET": buzz["relay"]["gitHookHmacSecret"],
    "POSTGRES_DB": buzz["postgres"]["db"],
    "POSTGRES_USER": buzz["postgres"]["user"],
    "POSTGRES_PASSWORD": buzz["postgres"]["password"],
    "REDIS_PASSWORD": buzz["redis"]["password"],
    "BUZZ_S3_ACCESS_KEY": buzz["s3"]["accessKey"],
    "BUZZ_S3_SECRET_KEY": buzz["s3"]["secretKey"],
    "BUZZ_S3_BUCKET": buzz["s3"]["bucket"],
    "BUZZ_S3_ADDRESSING_STYLE": "path",
    # Loopback only: Tailscale Serve is the sole way in.
    "BUZZ_HTTP_PORT": "127.0.0.1:3000",
}


def write(name, text):
    path = os.path.join(out, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


for k, v in relay_env.items():
    if "\n" in str(v) or not str(v):
        sys.exit(f"bad value for {k}")
write("buzz.env", "".join(f"{k}={v}\n" for k, v in relay_env.items()))

backup = env["backup"]
if sb_user and sb_host:
    write(
        "backup.env",
        f"RESTIC_REPOSITORY=sftp:storagebox:restic\nRESTIC_PASSWORD={backup['resticPassword']}\n",
    )
    write("storagebox", backup["sshPrivateKey"].rstrip("\n") + "\n")
    write(
        "storagebox.conf",
        f"Host storagebox\n  HostName {sb_host}\n  User {sb_user}\n  Port 23\n"
        "  IdentityFile /etc/buzz/ssh/storagebox\n  IdentitiesOnly yes\n"
        "  StrictHostKeyChecking accept-new\n  ServerAliveInterval 30\n",
    )
else:
    print("storage box outputs not available yet; skipping backup files", file=sys.stderr)
