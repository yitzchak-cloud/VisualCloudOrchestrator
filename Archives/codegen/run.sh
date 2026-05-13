#!/usr/bin/env bash
# codegen/run.sh
# ──────────────
# One-stop runner for the VCO node codegen pipeline.
#
# Usage:
#   ./codegen/run.sh                        # generate all overlay-defined resources
#   ./codegen/run.sh cloudrunv2.Service     # generate one resource
#   ./codegen/run.sh --refresh-schema       # re-download schema then generate all
#   ./codegen/run.sh --dry-run              # print to stdout, don't write files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SCHEMA_FILE="$SCRIPT_DIR/schema.json"
OVERLAYS_DIR="$SCRIPT_DIR/overlays"
TEMPLATES_DIR="$SCRIPT_DIR/templates"
OUT_DIR="$REPO_ROOT/nodes"

REFRESH_SCHEMA=0
DRY_RUN=""
SPECIFIC_RESOURCES=()

# ── parse args ────────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --refresh-schema) REFRESH_SCHEMA=1 ;;
        --dry-run)        DRY_RUN="--dry-run" ;;
        -*)               echo "Unknown flag: $arg" >&2; exit 1 ;;
        *)                SPECIFIC_RESOURCES+=("$arg") ;;
    esac
done

# ── step 1: schema ────────────────────────────────────────────────────────────
if [[ $REFRESH_SCHEMA -eq 1 ]] || [[ ! -f "$SCHEMA_FILE" ]]; then
    echo "📥  Downloading Pulumi GCP schema (this takes ~30 s) …"
    pulumi package get-schema gcp > "$SCHEMA_FILE"
    echo "✅  Schema saved to $SCHEMA_FILE"
else
    echo "ℹ️   Using cached schema: $SCHEMA_FILE  (pass --refresh-schema to re-download)"
fi

# ── step 2: codegen ───────────────────────────────────────────────────────────
echo ""
echo "🔨  Generating node files …"

if [[ ${#SPECIFIC_RESOURCES[@]} -gt 0 ]]; then
    python "$SCRIPT_DIR/schema_to_nodes.py" \
        --schema    "$SCHEMA_FILE" \
        --overlays  "$OVERLAYS_DIR" \
        --templates "$TEMPLATES_DIR" \
        --out       "$OUT_DIR" \
        $DRY_RUN \
        --resources "${SPECIFIC_RESOURCES[@]}"
else
    python "$SCRIPT_DIR/schema_to_nodes.py" \
        --schema      "$SCHEMA_FILE" \
        --overlays    "$OVERLAYS_DIR" \
        --templates   "$TEMPLATES_DIR" \
        --out         "$OUT_DIR" \
        $DRY_RUN \
        --all-overlays
fi

echo ""
echo "✅  Done.  Generated files are in: $OUT_DIR"