#!/usr/bin/env python3
"""Apply the experimental-glide crate renames to a pristine upstream checkout.

Derives our publishing changes instead of merging them from a long-lived branch:
rename the four crates, add the crates.io metadata cargo requires, keep the
original lib names, and annotate each in-repo path dependency with a version +
package so crates.io can resolve it.

Dependency versions are placeholders here; set-experimental-versions.py stamps
the real ones straight after. Dev-dependencies get `package` only (no version)
so cargo drops them when packaging — that is what keeps glide-core's
self-referencing dev-dep publishable.

Idempotent: re-running on an already-renamed tree is a no-op.

Usage: apply-experimental-renames.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Stamped over by set-experimental-versions.py; never published as-is.
PLACEHOLDER = "0.0.0"

REPO = '"https://github.com/valkey-io/valkey-glide"'

# manifest -> new crate name, lib name to preserve, metadata crates.io requires
CRATES = {
    "logger_core/Cargo.toml": {
        "name": "experimental-glide-logger-core",
        "lib": "logger_core",
        "metadata": {
            "description": '"Logging core for Valkey GLIDE"',
            "repository": REPO,
            "keywords": '["valkey", "glide", "logging"]',
            "categories": '["development-tools::debugging"]',
        },
    },
    "glide-core/telemetry/Cargo.toml": {
        "name": "experimental-glide-telemetrylib",
        "lib": "telemetrylib",
        "metadata": {
            "description": '"Telemetry (metrics and tracing) library for Valkey GLIDE"',
            "repository": REPO,
            "keywords": '["valkey", "glide", "telemetry", "opentelemetry"]',
            "categories": '["development-tools::profiling"]',
        },
    },
    # redis-rs already ships full crates.io metadata — rename + lib name only.
    "glide-core/redis-rs/redis/Cargo.toml": {
        "name": "experimental-glide-core-rs-dependency",
        "lib": "redis",
        "metadata": {},
    },
    "glide-core/Cargo.toml": {
        "name": "experimental-glide-core-lib",
        "lib": "glide_core",
        "metadata": {
            "description": '"Core client library for Valkey GLIDE"',
            "repository": REPO,
            "keywords": '["valkey", "glide", "redis", "client"]',
            "categories": '["database"]',
        },
    },
}

# dependency key as written in the manifests -> crate name on crates.io
DEP_PACKAGES = {
    "logger_core": "experimental-glide-logger-core",
    "telemetrylib": "experimental-glide-telemetrylib",
    "redis": "experimental-glide-core-rs-dependency",
    "glide-core": "experimental-glide-core-lib",
}

KV = re.compile(r'\s*[A-Za-z_][A-Za-z0-9_-]*\s*=')


def package_bounds(lines):
    """Return (start, kv_end, sec_end) for the [package] table.

    kv_end  = first section header after [package] (where its keys stop)
    sec_end = first section header that is not a [package...] subtable
    """
    start = next((i for i, l in enumerate(lines) if l.strip() == "[package]"), None)
    if start is None:
        raise SystemExit("!! no [package] table")
    kv_end = sec_end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith("["):
            kv_end = min(kv_end, i)
            if not lines[i].lstrip().startswith("[package"):
                sec_end = i
                break
    return start, kv_end, sec_end


def set_package_name(lines, new_name):
    start, kv_end, _ = package_bounds(lines)
    for i in range(start + 1, kv_end):
        if re.match(r'\s*name\s*=\s*"', lines[i]):
            if f'"{new_name}"' in lines[i]:
                return 0
            lines[i] = re.sub(r'(name\s*=\s*")[^"]*"', rf'\g<1>{new_name}"', lines[i])
            return 1
    raise SystemExit("!! no name in [package]")


def add_metadata(lines, metadata):
    """Add any missing crates.io metadata keys after the last [package] key."""
    start, kv_end, _ = package_bounds(lines)
    present = set()
    for i in range(start + 1, kv_end):
        m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_-]*)\s*=', lines[i])
        if m:
            present.add(m.group(1))
    missing = [(k, v) for k, v in metadata.items() if k not in present]
    if not missing:
        return 0
    last_kv = max(i for i in range(start + 1, kv_end) if KV.match(lines[i]))
    lines[last_kv + 1:last_kv + 1] = [f"{k} = {v}\n" for k, v in missing]
    return len(missing)


def ensure_lib_name(lines, lib_name):
    """Keep the original lib name so `use logger_core::..` etc. still compile."""
    for i, line in enumerate(lines):
        if line.strip() != "[lib]":
            continue
        for j in range(i + 1, len(lines)):
            if lines[j].lstrip().startswith("["):
                break
            if re.match(r'\s*name\s*=\s*"', lines[j]):
                return 0
        lines.insert(i + 1, f'name = "{lib_name}"\n')
        return 1
    # No [lib] table at all — create one after the [package] block.
    _, _, sec_end = package_bounds(lines)
    lines[sec_end:sec_end] = ["[lib]\n", f'name = "{lib_name}"\n', "\n"]
    return 1


def annotate_deps(lines):
    """Give our path deps a version + package so crates.io can resolve them.

    Dev-dependencies get `package` only: cargo drops version-less path deps when
    packaging, which is exactly what we want for the self-referencing dev-dep.
    """
    changed = 0
    section = ""
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("["):
            section = stripped.rstrip()
            continue
        m = re.match(r'\s*([A-Za-z0-9_-]+)\s*=\s*\{', line)
        if not m or m.group(1) not in DEP_PACKAGES or 'package = "' in line:
            continue
        path = re.search(r'path\s*=\s*"[^"]*"', line)
        if not path:
            continue
        insert = "" if "dev-dependencies" in section else f', version = "{PLACEHOLDER}"'
        insert += f', package = "{DEP_PACKAGES[m.group(1)]}"'
        lines[i] = line[:path.end()] + insert + line[path.end():]
        changed += 1
    return changed


def main() -> None:
    total = 0
    for rel, spec in CRATES.items():
        manifest = ROOT / rel
        if not manifest.is_file():
            raise SystemExit(f"!! missing {rel}")
        lines = manifest.read_text().splitlines(keepends=True)

        n = set_package_name(lines, spec["name"])
        n += add_metadata(lines, spec["metadata"])
        n += ensure_lib_name(lines, spec["lib"])
        n += annotate_deps(lines)

        if n:
            manifest.write_text("".join(lines))
        print(f"{rel}: {spec['name']} ({n} edits)")
        total += n

    print(f"renames applied ({total} edits)." if total else "already renamed — no changes.")


if __name__ == "__main__":
    main()
