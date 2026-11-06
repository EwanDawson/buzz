"""Write a versions.lock for one upstream commit to stdout.

Usage: resolve_images.py <upstream-repo-url> <commit-sha>

Reads deploy/compose/compose.yml at that commit to learn which images upstream
uses, then pins each to its current registry digest. The relay image is the
`sha-<7>` build of the commit; it fails if CI has not published it yet.
"""
import json
import re
import sys
import urllib.request

repo, commit = sys.argv[1], sys.argv[2]
slug = re.sub(r"^https://github.com/", "", repo).removesuffix(".git")
ACCEPT = ",".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def get(url, headers=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(), r.headers


def digest(image):
    """Return image pinned as name:tag@sha256:..."""
    name, _, rest = image.partition(":")
    tag = rest.split("@")[0] or "latest"
    if name.startswith("ghcr.io/"):
        path = name.removeprefix("ghcr.io/")
        tok = json.loads(get(f"https://ghcr.io/token?scope=repository:{path}:pull")[0])["token"]
        base = f"https://ghcr.io/v2/{path}"
    else:
        path = name if "/" in name else f"library/{name}"
        tok = json.loads(get(
            f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{path}:pull")[0])["token"]
        base = f"https://registry-1.docker.io/v2/{path}"
    _, h = get(f"{base}/manifests/{tag}", {"Authorization": f"Bearer {tok}", "Accept": ACCEPT}, "HEAD")
    return f"{name}:{tag}@{h['Docker-Content-Digest']}"


compose = get(f"https://raw.githubusercontent.com/{slug}/{commit}/deploy/compose/compose.yml")[0].decode()
images = {}
service = None
for line in compose.splitlines():
    m = re.match(r"^  ([a-z0-9-]+):\s*$", line)
    if m:
        service = m.group(1)
    m = re.match(r"^    image:\s*(\S+)", line)
    if m and service:
        images[service] = m.group(1)

need = {"postgres": "POSTGRES_IMAGE", "redis": "REDIS_IMAGE", "minio": "SILO_IMAGE", "minio-init": "MC_IMAGE"}
missing = [s for s in need if s not in images]
if missing:
    sys.exit(f"upstream compose.yml no longer has services {missing}; update the overlay by hand")

out = {
    "UPSTREAM_REPO": repo,
    "UPSTREAM_COMMIT": commit,
    "BUZZ_IMAGE": digest(f"ghcr.io/{slug.lower()}:sha-{commit[:7]}"),
}
for svc, key in need.items():
    img = images[svc]
    # Upstream already digest-pins some images; keep its pin when present.
    out[key] = img if "@sha256:" in img else digest(img)

print("# Pinned versions for the Hetzner deployment. Written by hetzner/bin/bump.")
print("# KEY=VALUE only: this file is passed to `docker compose --env-file` and sourced by scripts.")
print("# Bump it through a PR; merging the PR is the approval to upgrade.")
for k, v in out.items():
    print(f"{k}={v}")
