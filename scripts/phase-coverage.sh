#!/usr/bin/env bash
# Per-phase coverage gate (see _implementation.md, "Rules for Every Phase").
#
# Usage: scripts/phase-coverage.sh <module>[,<module>...] <tests> [<tests>...]
#
# Runs the given tests and fails unless the listed modules reach 80% coverage.
# Modules are paths or dotted names accepted by --cov, separated by commas.
#
# Example:
#   scripts/phase-coverage.sh custom_components/haanim/engine/symbol_table.py tests/engine/test_init.py
set -euo pipefail

if [[ $# -lt 2 ]]; then
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

modules="$1"
shift

cov_args=()
IFS=',' read -ra module_list <<<"$modules"
for module in "${module_list[@]}"; do
    # coverage's --cov takes a package directory or dotted name, not a file, so a
    # file is measured through its package and selected with --include below.
    if [[ "$module" == *.py ]]; then
        cov_args+=("--cov=$(dirname "$module")")
    else
        cov_args+=("--cov=$module")
    fi
done

include=""
for module in "${module_list[@]}"; do
    if [[ "$module" == *.py ]]; then
        include+="${include:+,}$module"
    else
        include+="${include:+,}${module//.//}/*"
    fi
done

cd "$(dirname "$0")/.."

# Override the project-wide coverage options from pyproject.toml for this run.
uv run pytest "$@" \
    -o addopts="" \
    -p no:cacheprovider \
    -q \
    "${cov_args[@]}" \
    --cov-branch \
    --cov-report= \
    --cov-fail-under=0

uv run coverage report --include="$include" --fail-under=80 --show-missing
