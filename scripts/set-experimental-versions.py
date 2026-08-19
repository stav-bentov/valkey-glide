#!/usr/bin/env python3
"""Set experimental-glide crate versions for a sync-and-publish run (scheme B).

ALL four crates align to the upstream release version passed on the CLI,
including the redis-rs fork. The fork used to keep its own version (0.25.2),
but that version never changed, so `is_published` skipped it forever and
glide-core got built against a stale published fork — v2.5.1 failed exactly
that way (missing ClusterClientBuilder::recovery_requests_queue_size). We
publish the fork under our own name, so its version number is ours to pick.

Edits are line-targeted (only [package] version, and version fields on dep
lines carrying our `package = "experimental-glide-*"` annotation) so nothing
else in the manifests is touched.

Usage: set-experimental-versions.py <GLIDE_VERSION>   e.g. 2.5.0
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every crate we publish; all align to the upstream tag.
CRATE_DIRS = [
    "logger_core",
    "glide-core/telemetry",
    "glide-core/redis-rs/redis",
    "glide-core",
]


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

    print(f"all experimental-glide crates -> {glide_version}")

    # 1) [package] versions
    for d in CRATE_DIRS:
        set_package_version(ROOT / d / "Cargo.toml", glide_version)

    # 2) dependent annotations, across every manifest
    pkg_to_version = {
        "experimental-glide-logger-core": glide_version,
        "experimental-glide-telemetrylib": glide_version,
        "experimental-glide-core-rs-dependency": glide_version,
    }
    for d in CRATE_DIRS:
        set_dep_versions(ROOT / d / "Cargo.toml", pkg_to_version)

    print("versions set.")


if __name__ == "__main__":
    main()
