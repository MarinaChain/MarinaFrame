#!/usr/bin/env bash
# Build the relocatable worker Python that the macOS app bundles at
# MarinaFrame.app/Contents/Resources/worker (packaging plan step 3,
# docs/plans/2026-11-09-packaging.md).
#
# Usage (from any folder; macOS arm64 only):
#   scripts/build_worker_runtime.sh          build build/worker-runtime/worker
#   scripts/build_worker_runtime.sh lock     re-hash both macOS arm64 locks from their pins
#   scripts/build_worker_runtime.sh test-env put pytest, trimesh and jsonschema in
#                                            build/worker-runtime/test-site (never shipped)
#
# The runtime is python-build-standalone CPython (a pinned release, checked against the
# SHA-256 below), the exact wheels of requirements-worker-macos-arm64-py312.lock (installed
# with --require-hashes), and a wheel of vessel_reconstruction built from the committed
# source at HEAD (not an editable install). Nothing from a system Python is used.
# Everything under build/ is git-ignored; only this script and the locks are tracked.
set -euo pipefail

# python-build-standalone release and the SHA-256 of its stripped install-only archive for
# aarch64-apple-darwin (from that release's SHA256SUMS). Change all three together.
PBS_RELEASE="20261009"
PBS_PYTHON="3.12.15"
PBS_SHA256="233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f"
PBS_ARCHIVE="cpython-${PBS_PYTHON}+${PBS_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_ARCHIVE//+/%2B}"

# Oldest macOS whose wheel tags the lock accepts. python-build-standalone itself needs 11.0.
MACOS_WHEEL_PLATFORM="macosx_13_0_arm64"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_LOCK="$REPO/requirements-worker-macos-arm64-py312.lock"
TOOLS_LOCK="$REPO/requirements-worker-tools-macos-arm64-py312.lock"
OUT="$REPO/build/worker-runtime"
CACHE="$OUT/cache"
RUNTIME="$OUT/worker"
BUILD_VENV="$OUT/build-venv"
TEST_SITE="$OUT/test-site"

fail() { echo "build_worker_runtime: $*" >&2; exit 1; }

require_macos_arm64() {
    [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] \
        || fail "this runtime is built on macOS arm64 only"
}

sha256_of() { shasum -a 256 "$1" | cut -d' ' -f1; }

# Download (once) and verify the pinned CPython archive; print its path.
fetch_python_archive() {
    local archive="$CACHE/$PBS_ARCHIVE"
    mkdir -p "$CACHE"
    if [[ ! -f "$archive" ]]; then
        curl --fail --location --silent --show-error --output "$archive.part" "$PBS_URL"
        mv "$archive.part" "$archive"
    fi
    local actual
    actual="$(sha256_of "$archive")"
    if [[ "$actual" != "$PBS_SHA256" ]]; then
        rm -f "$archive"
        fail "checksum mismatch for $PBS_ARCHIVE (got $actual); the download was deleted"
    fi
    echo "$archive"
}

# Extract a fresh copy of the pinned CPython into folder $1 (its python/ is renamed to $1).
extract_python() {
    local target="$1" archive staging
    archive="$(fetch_python_archive)"
    staging="$(mktemp -d "$OUT/extract.XXXXXX")"
    tar -xzf "$archive" -C "$staging"
    rm -rf "$target"
    mv "$staging/python" "$target"
    rmdir "$staging"
}

# A virtual environment from the pinned CPython, for pip download, building the package
# wheel and the test site. It is never shipped.
make_build_venv() {
    if [[ ! -x "$BUILD_VENV/bin/python" ]]; then
        extract_python "$OUT/base-python"
        "$OUT/base-python/bin/python3" -I -m venv "$BUILD_VENV"
    fi
}

# Re-hash one lock: keep its comment header and exact pins, download the one wheel per pin
# that pip selects for $MACOS_WHEEL_PLATFORM / CPython 3.12, and write its SHA-256.
rehash_lock() {
    local lock="$1" wheels pins
    wheels="$(mktemp -d "$OUT/wheels.XXXXXX")"
    pins="$wheels/pins.txt"
    grep -Ev '^[[:space:]]*(#|$)' "$lock" | sed -E 's/[[:space:]]+--hash=.*$//' > "$pins"
    "$BUILD_VENV/bin/python" -I -m pip download --quiet --no-deps --only-binary=:all: \
        --platform "$MACOS_WHEEL_PLATFORM" --python-version 3.12 --implementation cp \
        --abi cp312 --dest "$wheels" -r "$pins"
    {
        grep -E '^#' "$lock"
        while read -r pin; do
            local name="${pin%%==*}" version="${pin#*==}" file
            # Wheel file names use the normalised name with underscores.
            file="$(ls "$wheels" | grep -i -E "^$(echo "$name" | tr -- '-.' '__')-${version}-.*\.whl$")" \
                || fail "no wheel downloaded for $pin"
            [[ "$(echo "$file" | wc -l)" -eq 1 ]] || fail "more than one wheel for $pin"
            echo "$pin --hash=sha256:$(sha256_of "$wheels/$file")"
        done < "$pins"
    } > "$lock.new"
    mv "$lock.new" "$lock"
    rm -rf "$wheels"
    echo "re-hashed $(grep -c -- '--hash=' "$lock") pins in $(basename "$lock")"
}

# The vessel_reconstruction wheel, built from the committed source at HEAD.
build_package_wheel() {
    local source dist
    source="$(mktemp -d "$OUT/source.XXXXXX")"
    dist="$OUT/dist"
    rm -rf "$dist"
    git -C "$REPO" archive HEAD pyproject.toml README.md src | tar -x -C "$source"
    "$BUILD_VENV/bin/python" -I -m pip install --quiet --require-hashes --no-deps \
        --only-binary=:all: -r <(grep -E '^(setuptools|wheel)==' "$TOOLS_LOCK")
    "$BUILD_VENV/bin/python" -I -m pip wheel --quiet --no-deps --no-build-isolation \
        --wheel-dir "$dist" "$source"
    rm -rf "$source"
    ls "$dist"/vessel_reconstruction-*.whl
}

# Remove what the app never runs and anything that records the build machine's paths.
trim_runtime() {
    "$RUNTIME/bin/python3" -I -m pip uninstall --quiet --yes pip
    # One interpreter file, bin/python3 (the path the app looks for), and no symbolic links:
    # the bundler would copy each link as a second 18 MB file.
    find "$RUNTIME/bin" -mindepth 1 ! -name python3.12 -exec rm -f {} +
    mv "$RUNTIME/bin/python3.12" "$RUNTIME/bin/python3"
    rm -rf "$RUNTIME/include" "$RUNTIME/share" "$RUNTIME/lib/pkgconfig"
    find "$RUNTIME/lib/python3.12/site-packages" -name direct_url.json -delete
    [[ -z "$(find "$RUNTIME" -type l)" ]] || fail "symbolic links left in the runtime"
    find "$RUNTIME" -name __pycache__ -type d -prune -exec rm -rf {} +
    # Bytecode that Python never re-checks or rewrites: a signed bundle is read only, and a
    # write inside it would break the signature. Old escape sequences in VTK only warn.
    "$RUNTIME/bin/python3" -I -W ignore::SyntaxWarning -m compileall -q -j 0 \
        --invalidation-mode unchecked-hash "$RUNTIME/lib/python3.12" > /dev/null
}

write_manifest() {
    local wheel="$1"
    cat > "$RUNTIME/MARINAFRAME_RUNTIME.json" <<JSON
{
  "python": "$PBS_PYTHON",
  "python_build_standalone_release": "$PBS_RELEASE",
  "python_archive": "$PBS_ARCHIVE",
  "python_archive_sha256": "$PBS_SHA256",
  "lock": "$(basename "$RUNTIME_LOCK")",
  "lock_sha256": "$(sha256_of "$RUNTIME_LOCK")",
  "package_wheel": "$(basename "$wheel")",
  "package_wheel_sha256": "$(sha256_of "$wheel")",
  "source_commit": "$(git -C "$REPO" rev-parse HEAD)"
}
JSON
}

build_runtime() {
    make_build_venv
    extract_python "$RUNTIME"
    "$RUNTIME/bin/python3" -I -m pip install --quiet --require-hashes --no-deps \
        --only-binary=:all: -r "$RUNTIME_LOCK"
    local wheel
    wheel="$(build_package_wheel)"
    "$RUNTIME/bin/python3" -I -m pip install --quiet --no-deps --no-index "$wheel"
    write_manifest "$wheel"
    trim_runtime
    "$RUNTIME/bin/python3" -I -c \
        'import cadquery, OCP, fitz, ezdxf, scipy, vessel_reconstruction.rust_worker'
    # OpenCV is left out on purpose (its macOS wheel vendors GPL video codecs).
    if "$RUNTIME/bin/python3" -I -c 'import cv2' 2> /dev/null; then
        fail "cv2 is importable in the runtime; it must not be bundled"
    fi
    rm -rf "$OUT/dist"
    echo "worker runtime: $RUNTIME ($(du -sh "$RUNTIME" | cut -f1))"
}

# Test-only packages beside (not in) the runtime; use with PYTHONPATH=$TEST_SITE.
build_test_site() {
    make_build_venv
    rm -rf "$TEST_SITE"
    "$BUILD_VENV/bin/python" -I -m pip install --quiet --require-hashes --no-deps \
        --only-binary=:all: --target "$TEST_SITE" \
        -r <(grep -Ev '^(setuptools|wheel)==' "$TOOLS_LOCK")
    echo "test site: $TEST_SITE"
}

main() {
    require_macos_arm64
    mkdir -p "$OUT"
    case "${1:-build}" in
        build) build_runtime ;;
        lock) make_build_venv; rehash_lock "$RUNTIME_LOCK"; rehash_lock "$TOOLS_LOCK" ;;
        test-env) build_test_site ;;
        *) fail "unknown command '$1' (build, lock or test-env)" ;;
    esac
}

main "$@"
