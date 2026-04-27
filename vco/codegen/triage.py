"""
codegen/triage.py
-----------------
Scans the full Pulumi GCP schema and emits a curated list of resource types
that are worth exposing as VCO canvas nodes.

Filtering rules (all must pass):
  INCLUDE modules  — only well-known GCP service modules
  EXCLUDE suffixes — IamBinding, IamMember, IamPolicy, Version, Attachment,
                     Association, BackendConfig, RegionBackendConfig, etc.
  EXCLUDE tiny     — fewer than 2 meaningful input properties (after skipping
                     project/labels/annotations/name/etag…)
  EXCLUDE deprecated — description contains "deprecated"

Output: codegen/resources.txt  (one pulumi_type per line)
        codegen/resources_report.txt  (human-readable with counts per module)

Usage:
  python codegen/triage.py --schema codegen/schema.json
  python codegen/triage.py --schema codegen/schema.json --out codegen/resources.txt
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path

# ── modules we actually want nodes for ───────────────────────────────────────
# Keep this list intentional — not every GCP module belongs on a canvas.
INCLUDE_MODULES = {
    # Compute / serverless
    "cloudrunv2", "cloudfunctions", "cloudfunctionsv2", "appengine",
    # Messaging / eventing
    "pubsub", "eventarc",
    # Workflows / scheduling
    "workflows", "cloudscheduler", "cloudtasks",
    # Storage
    "storage", "filestore",
    # Databases
    "bigquery", "bigtable", "sql", "spanner",
    "firestore", "datastore", "redis", "memcache",
    # Networking
    "compute",          # filtered heavily below
    "dns", "networkconnectivity",
    # Security / identity
    "iam", "secretmanager", "kms",
    # Containers
    "container", "artifactregistry",
    # Data / ML
    "dataflow", "dataproc", "composer",
    "aiplatform", "vertexai",
    # Monitoring / logging
    "monitoring", "logging",
}

# ── resource name suffixes to always exclude ──────────────────────────────────
EXCLUDE_SUFFIXES = (
    "IamBinding", "IamMember", "IamPolicy",
    "Version", "SecretVersion",
    "Attachment", "Association",
    "BackendConfig", "RegionBackendConfig",
    "SignedUrlKey",
    "DefaultObjectAccessControl", "ObjectAccessControl", "BucketAccessControl",
    "DefaultServiceAccount",
    "OrganizationPolicy",
    "PacketMirroring",
    "ResourcePolicy",
    "TargetHttpsProxiesSslCertificate",
)

# ── for `compute` module only keep these (it has 200+ resources) ──────────────
COMPUTE_ALLOW = {
    "Network", "Subnetwork", "FirewallPolicy", "FirewallPolicyRule",
    "Firewall", "Router", "RouterNat", "Address", "GlobalAddress",
    "SslCertificate", "ManagedSslCertificate",
    "InstanceTemplate", "Instance", "InstanceGroupManager",
    "RegionInstanceGroupManager", "Autoscaler", "RegionAutoscaler",
    "BackendService", "RegionBackendService",
    "UrlMap", "RegionUrlMap",
    "TargetHttpProxy", "TargetHttpsProxy",
    "GlobalForwardingRule", "ForwardingRule",
    "HealthCheck", "RegionHealthCheck",
    "Disk", "Snapshot",
    "VpnGateway", "HaVpnGateway", "VpnTunnel",
    "ExternalVpnGateway",
    "InterconnectAttachment",
    "SecurityPolicy",
    "NetworkPeeringRoutesConfig",
}

# ── properties that are never meaningful UI fields ────────────────────────────
SKIP_PROPS = frozenset({
    "project", "labels", "annotations", "conditions",
    "etag", "selfLink", "fingerprint", "uid", "name",
    "createTime", "updateTime", "deletionProtection",
})

COMPLEX_TYPES = frozenset({"object", "array"})


def _meaningful_props(input_props: dict) -> int:
    """Count props that can actually be rendered in the UI."""
    count = 0
    for pname, pschema in input_props.items():
        if pname in SKIP_PROPS:
            continue
        if pschema.get("type") in COMPLEX_TYPES:
            continue
        if "$ref" in pschema:
            continue
        count += 1
    return count


def triage(schema: dict) -> list[tuple[str, str]]:
    """
    Returns list of (pulumi_type, reason) for included resources.
    pulumi_type: e.g. 'cloudrunv2.Service'
    """
    included: list[tuple[str, str]] = []

    for key, rdef in schema.get("resources", {}).items():
        # key format: gcp:MODULE/lower:Resource
        m = re.match(r"gcp:([^/]+)/[^:]+:(.+)$", key)
        if not m:
            continue
        module, resource = m.group(1), m.group(2)

        # 1. module allow-list
        if module not in INCLUDE_MODULES:
            continue

        # 2. compute special allow-list
        if module == "compute" and resource not in COMPUTE_ALLOW:
            continue

        # 3. exclude suffixes
        if any(resource.endswith(s) for s in EXCLUDE_SUFFIXES):
            continue

        # 4. skip deprecated
        desc = rdef.get("description", "").lower()
        if "deprecated" in desc:
            continue

        # 5. must have at least 2 renderable input props
        props = _meaningful_props(rdef.get("inputProperties", {}))
        if props < 2:
            continue

        pulumi_type = f"{module}.{resource}"
        included.append((pulumi_type, f"{props} props"))

    # stable sort: module then resource name
    included.sort(key=lambda x: x[0])
    return included


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--schema", required=True)
    p.add_argument("--out",    default="codegen/resources.txt")
    p.add_argument("--report", default="codegen/resources_report.txt")
    args = p.parse_args()

    schema = json.loads(Path(args.schema).read_text())
    results = triage(schema)

    # ── write resources.txt ───────────────────────────────────────────────────
    lines = [pt for pt, _ in results]
    Path(args.out).write_text("\n".join(lines) + "\n")

    # ── write report ──────────────────────────────────────────────────────────
    by_module: dict[str, list] = defaultdict(list)
    for pt, reason in results:
        module = pt.split(".")[0]
        by_module[module].append((pt, reason))

    report_lines = [
        f"VCO Node Triage Report",
        f"Total resources selected: {len(results)}",
        f"{'─'*55}",
        "",
    ]
    for module in sorted(by_module):
        items = by_module[module]
        report_lines.append(f"[{module}]  ({len(items)} resources)")
        for pt, reason in items:
            report_lines.append(f"  {pt:50s}  {reason}")
        report_lines.append("")

    Path(args.report).write_text("\n".join(report_lines))

    print(f"Selected {len(results)} resources → {args.out}")
    print(f"Report   → {args.report}")
    print("")
    for module in sorted(by_module):
        print(f"  {module:25s} {len(by_module[module]):3d} resources")


if __name__ == "__main__":
    main()