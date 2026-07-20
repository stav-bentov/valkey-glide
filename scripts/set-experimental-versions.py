#!/usr/bin/env python3
"""Set experimental-glide crate versions for a sync-and-publish run (scheme B).

glide-owned crates (logger-core, telemetrylib, core-lib) are aligned to the
upstream release version passed on the CLI. redis-rs keeps its OWN version
(whatever its Cargo.toml already declares after the upstream merge) — we only
read it so dependent annotations stay consistent.

Edits are line-targeted (only [package] version, and version fields on dep
lines carrying our `package = "experimental-glide-*"` annotation) so nothing
else in the manifests is touched.

Usage: set-experimental-versions.py <GLIDE_VERSION>   e.g. 2.5.0
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# glide-owned crates that align to the upstream tag: dir -> manifest
GLIDE_OWNED = [
    "logger_core",
    "glide-core/telemetry",
    "glide-core",
]
REDIS_MANIFEST = "glide-core/redis-rs/redis/Cargo.toml"

# package annotation -> which version to stamp on dep lines referencing it
# (redis filled in at runtime from its own manifest)
DEP_PKG_TO_VERSION = {}


def read_package_version(manifest: Path) -> str:
    """Return the version from the [package] table (first version after it)."""
    in_pkg = False
    for line in manifest.read_text().splitlines():
        if line.strip() == "[package]":
            in_pkg = True
        elif in_pkg:
            m = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
            if m:
                return m.group(1)
            if line.strip().startswith("["):  # left [package] without finding it
                break
    raise SystemExit(f"!! no [package] version in {manifest}")


def set_package_version(manifest: Path, version: str) -> None:
    """Rewrite the [package] version only."""
    lines = manifest.read_text().splitlines(keepends=True)
    in_pkg = False
    done = False
    for i, line in enumerate(lines):
        if line.strip() == "[package]":
            in_pkg = True
        elif in_pkg and not done:
            if re.match(r'\s*version\s*=\s*"', line):
                lines[i] = re.sub(r'("version"\s*=\s*"|version\s*=\s*")[^"]+"',
                                  rf'\g<1>{version}"', line)
                done = True
            elif line.strip().startswith("["):
                break
    manifest.write_text("".join(lines))


def set_dep_versions(manifest: Path, pkg_to_version: dict) -> None:
    """On dep lines that carry `package = "<name>"`, set their version field."""
    text = manifest.read_text()
    out = []
    for line in text.splitlines(keepends=True):
        for pkg, ver in pkg_to_version.items():
            if f'package = "{pkg}"' in line and re.search(r'version\s*=\s*"', line):
                line = re.sub(r'(version\s*=\s*")[^"]+"', rf'\g<1>{ver}"', line)
        out.append(line)
    manifest.write_text("".join(out))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: set-experimental-versions.py <GLIDE_VERSION>")
    glide_version = sys.argv[1].lstrip("v")

    redis_version = read_package_version(ROOT / REDIS_MANIFEST)
    print(f"glide-owned -> {glide_version}; redis-rs keeps {redis_version}")

    # 1) [package] versions for glide-owned crates
    for d in GLIDE_OWNED:
        set_package_version(ROOT / d / "Cargo.toml", glide_version)

    # 2) dependent annotations, across every manifest
    pkg_to_version = {
        "experimental-glide-logger-core": glide_version,
        "experimental-glide-telemetrylib": glide_version,
        "experimental-glide-core-rs-dependency": redis_version,
    }
    for d in GLIDE_OWNED + ["glide-core/redis-rs/redis"]:
        set_dep_versions(ROOT / d / "Cargo.toml", pkg_to_version)

    print("versions set.")


if __name__ == "__main__":
    main()
