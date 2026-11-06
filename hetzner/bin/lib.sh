# Shared settings for the operator-side scripts. Source, don't execute.
# These run on an operator machine (or Claude's workspace) that is on the tailnet,
# logged in to Pulumi, and has the tailscale CLI.
set -euo pipefail
[[ -d "$HOME/.pulumi/bin" ]] && PATH="$HOME/.pulumi/bin:$PATH"
BUZZ_ESC_ENV=${BUZZ_ESC_ENV:-EwanDawson/buzz-relay/prod}
BUZZ_STACK=${BUZZ_STACK:-EwanDawson/buzz-relay/prod}
BUZZ_HOST=${BUZZ_HOST:-buzz}
HETZNER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Run a command on the server as root over Tailscale SSH.
remote() {
  ssh -o StrictHostKeyChecking=accept-new -o ProxyCommand="tailscale nc %h %p" \
    "root@$BUZZ_HOST" "$@"
}

esc_json() { pulumi env open "$BUZZ_ESC_ENV" --format json 2>/dev/null; }
