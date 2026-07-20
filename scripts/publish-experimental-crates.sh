#!/usr/bin/env bash
# Publish the experimental-glide-* crates, in dependency order, but ONLY the ones
# whose local version is not already on crates.io. Idempotent: safe to re-run.
#
# crates.io is immutable per (name, version). "Version bump -> new publish" therefore
# means: compare local Cargo.toml version to what's live; publish only if newer/missing.
#
# Usage:
#   ./scripts/publish-experimental-crates.sh            # real publish
#   DRY_RUN=1 ./scripts/publish-experimental-crates.sh  # dry-run, no upload
#
# Requires: cargo (logged in, or CARGO_REGISTRY_TOKEN set), curl, jq.

set -euo pipefail

# Publish order = bottom-up dependency order. Each entry: "<dir>|<crate-name-on-crates.io>"
CRATES=(
  "logger_core|experimental-glide-logger-core"
  "glide-core/telemetry|experimental-glide-telemetrylib"
  "glide-core/redis-rs/redis|experimental-glide-core-rs-dependency"
  "glide-core|experimental-glide-core-lib"
)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN="${DRY_RUN:-0}"

# Read the local version for a crate name out of its Cargo.toml [package] table.
local_version() {
  local dir="$1"
  # first `version = "x"` after the [package] header
  awk '/^\[package\]/{p=1} p&&/^version[[:space:]]*=/{gsub(/[",]/,"",$3); print $3; exit}' \
    "$REPO_ROOT/$dir/Cargo.toml"
}

# Is (name, version) already live on crates.io?
is_published() {
  local name="$1" ver="$2"
  local live
  live="$(curl -sf -H 'User-Agent: experimental-glide-publish-poc' \
    "https://crates.io/api/v1/crates/$name" | jq -r '.versions[].num' 2>/dev/null || true)"
  grep -qxF "$ver" <<<"$live"
}

for entry in "${CRATES[@]}"; do
  dir="${entry%%|*}"
  name="${entry##*|}"
  ver="$(local_version "$dir")"

  if [[ -z "$ver" ]]; then
    echo "!! could not read version for $name ($dir/Cargo.toml) — skipping"
    continue
  fi

  if is_published "$name" "$ver"; then
    echo "== $name $ver already on crates.io — skip"
    continue
  fi

  echo "++ $name $ver is new — publishing from $dir"
  publish_flags=(--allow-dirty)
  [[ "$DRY_RUN" == "1" ]] && publish_flags+=(--dry-run)

  ( cd "$REPO_ROOT/$dir" && cargo publish "${publish_flags[@]}" )

  # crates.io needs a moment to index a new version before a dependent can resolve it.
  if [[ "$DRY_RUN" != "1" ]]; then
    echo "   waiting for crates.io to index $name $ver ..."
    for _ in $(seq 1 30); do
      is_published "$name" "$ver" && break
      sleep 10
    done
  fi
done

echo "done."
