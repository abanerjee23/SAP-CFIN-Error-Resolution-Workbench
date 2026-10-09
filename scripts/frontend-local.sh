#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
node_version="$(cat "$project_root/frontend/.nvmrc")"
action="${1:-dev}"
if [[ $# -gt 0 ]]; then shift; fi

case "$action" in
  install|dev|build|typecheck|start|railway-install|railway-check) ;;
  *) echo "Usage: bash scripts/frontend-local.sh [install|dev|build|typecheck|start|railway-install|railway-check]" >&2; exit 1 ;;
esac

# iCloud can offload ignored files in Documents, including Node and node_modules.
# Keep generated runtime files in the OS temporary directory on Apple Silicon.
local_storage=false
if [[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]]; then
  local_storage=true
  project_key="$(printf '%s' "$project_root" | shasum -a 256 | cut -c 1-12)"
  local_dir="${CFIN_FRONTEND_LOCAL_DIR:-${TMPDIR:-/tmp}/cfin-frontend-$project_key}"
  mkdir -p "$local_dir"
  runtime_dir="$local_dir/node-v${node_version}-darwin-arm64"
  if [[ ! -x "$runtime_dir/bin/node" ]]; then
    archive="node-v${node_version}-darwin-arm64.tar.gz"
    echo "Installing local Node $node_version..."
    curl --fail --location --retry 2 "https://nodejs.org/dist/v${node_version}/$archive" -o "$local_dir/$archive"
    (cd "$local_dir" && printf '%s  %s\n' '23b25245dcfb9af7262f8ff142e9e2e0af025368117329e7a7458a51e5922f53' "$archive" | shasum -a 256 -c -)
    tar -xzf "$local_dir/$archive" -C "$local_dir"
    rm "$local_dir/$archive"
  fi
  export PATH="$runtime_dir/bin:$PATH"
elif ! command -v node >/dev/null || [[ "$(node -p 'process.versions.node.split(".")[0]')" != 22 ]]; then
  echo "Install Node $node_version (for example: cd frontend && nvm install && nvm use), then rerun this command." >&2
  exit 1
fi

# Use the same supported Node runtime for repository-wide tooling. The caller's
# shell may still have an older Node even after the frontend launcher runs.
case "$action" in
  railway-install) exec npm ci --prefix "$project_root/.railway" --ignore-scripts ;;
  railway-check) exec npm run check --prefix "$project_root/.railway" ;;
esac

cd "$project_root/frontend"
echo "Frontend runtime: $(node --version)"
if [[ "$local_storage" == true ]]; then
  lock_digest="$(shasum -a 256 package.json package-lock.json | shasum -a 256 | cut -d ' ' -f 1)"
  cached_digest="$(cat "$local_dir/.dependency-lock" 2>/dev/null || true)"
  if [[ "$action" == install || "$cached_digest" != "$lock_digest" || ! -f "$local_dir/node_modules/next/package.json" ]]; then
    cp package.json package-lock.json "$local_dir/"
    echo "Installing locked frontend dependencies in local storage..."
    npm ci --prefix "$local_dir" --cache "$local_dir/npm-cache" --no-audit --no-fund
    printf '%s\n' "$lock_digest" > "$local_dir/.dependency-lock"
  fi
  for generated_dir in node_modules .next; do
    mkdir -p "$local_dir/$generated_dir"
    if [[ ! -L "$generated_dir" || "$(readlink "$generated_dir")" != "$local_dir/$generated_dir" ]]; then
      rm -rf "$generated_dir"
      ln -s "$local_dir/$generated_dir" "$generated_dir"
    fi
  done
  echo "Local frontend files: $local_dir"
  case "$action" in
    install) exit 0 ;;
    # Webpack supports dependencies linked outside the project directory.
    dev) exec npm run dev -- --webpack --hostname 127.0.0.1 "$@" ;;
    build) exec env CFIN_LOCAL_BUILD=1 npm run build -- --webpack "$@" ;;
  esac
fi
case "$action" in
  install) exec npm ci --no-audit --no-fund "$@" ;;
  dev) exec npm run dev -- --hostname 127.0.0.1 "$@" ;;
  build|typecheck|start) exec npm run "$action" -- "$@" ;;
esac
