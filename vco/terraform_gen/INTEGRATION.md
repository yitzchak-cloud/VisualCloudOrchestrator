# VCO Terraform Export — Integration Guide
# ==========================================
# This file shows EXACTLY which lines to add to existing files.
# Everything else is in the new terraform_gen/ package and api_routes_terraform.py.

# ── 1. Copy the new module into your project root ──────────────────────────────
# cp -r terraform_gen/ /path/to/your/vco/project/
# cp api_routes_terraform.py /path/to/your/vco/project/api/routes/terraform.py

# ── 2. Add ONE line to main.py ─────────────────────────────────────────────────
# In main.py, after the existing imports of routes:

#   from api.routes import deploy, graph, nodes, realtime, logs, namespaces
#   from api.routes import terraform          # ← ADD THIS LINE

# And after the existing app.include_router() calls:
#   app.include_router(terraform.router)      # ← ADD THIS LINE

# ── 3. The terraform_gen/ package has zero overlap with existing code ───────────
# It does NOT import from:
#   - core.log_bridge
#   - core.ws_manager
#   - deploy.*
#   - pulumi_synth
#   - core.log_store
# It only reads the same node/edge dicts that every other route already receives.

# ── 4. No new dependencies ──────────────────────────────────────────────────────
# terraform_gen uses only Python stdlib + pydantic (already installed).
# No terraform binary is needed server-side — we just generate .tf text files.

# ── 5. UI changes in indxe.html ────────────────────────────────────────────────
# See INTEGRATION_UI.md for the UI patch.
