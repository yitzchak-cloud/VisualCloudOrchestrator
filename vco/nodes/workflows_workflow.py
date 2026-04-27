# AUTO-GENERATED — do not edit by hand.
# Source : pulumi schema (workflows.Workflow) + overlay
# Regen  : python codegen/schema_to_nodes.py --resources workflows.Workflow
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

import pulumi
import pulumi_gcp as gcp

from nodes.base_node import GCPNode, LogSource, Port, _resource_name, _node_name, _node_label
from nodes.port_types import PortType

logger = logging.getLogger(__name__)


@dataclass
class WorkflowNode(GCPNode):
    """HTTP services orchestration"""

    # ── UI metadata ───────────────────────────────────────────────────────────
    node_color:  ClassVar = "#c084fc"
    icon:        ClassVar = "workflows"
    category:    ClassVar = "Integration_Services"
    description: ClassVar = "HTTP services orchestration"
    url_field:   ClassVar = None

    params_schema: ClassVar = [
        {
            'key': 'name',
            'label': 'Resource Name',
            'type': 'text',
            'default': '',
            'placeholder': 'my-resource',
        },
        {
            'key': 'region',
            'label': 'Region',
            'type': 'select',
            'options': ['me-west1', 'us-central1', 'us-east1', 'europe-west1'],
            'default': 'me-west1',
        },
        {
            'key': 'source_yaml',
            'label': 'Custom YAML (overrides auto-generated)',
            'type': 'yaml',
            'default': '',
            'placeholder': 'main:\n  steps:\n  - ...',
        },
        {
            'key': 'http_path',
            'label': 'Default HTTP path for wired services',
            'type': 'text',
            'default': '/',
            'placeholder': '/run',
        },
        {
            'key': 'callLogLevel',
            'label': 'Call Log Level',
            'type': 'text',
            'default': '',
            'description': 'Describes the level of platform logging to apply to calls and call responses during\nexecutions of this workflow',
        },
        {
            'key': 'cryptoKeyName',
            'label': 'Crypto Key Name',
            'type': 'text',
            'default': '',
            'description': 'The KMS key used to encrypt workflow and execution data',
        },
        {
            'key': 'deletionProtection',
            'label': 'Deletion Protection',
            'type': 'boolean',
            'default': '',
            'description': 'Whether Terraform will be prevented from destroying the workflow',
        },
        {
            'key': 'description',
            'label': 'Description',
            'type': 'text',
            'default': '',
            'description': 'Description of the workflow provided by the user',
        },
        {
            'key': 'executionHistoryLevel',
            'label': 'Execution History Level',
            'type': 'text',
            'default': '',
            'description': 'Describes the level of execution history to be stored for this workflow',
        },
        {
            'key': 'namePrefix',
            'label': 'Name Prefix',
            'type': 'text',
            'default': '',
            'description': 'Creates a unique name beginning with the\nspecified prefix',
        },
        {
            'key': 'serviceAccount',
            'label': 'Service Account',
            'type': 'yaml',
            'default': '',
            'description': 'Name of the service account associated with the latest workflow version',
        },
        {
            'key': 'sourceContents',
            'label': 'Source Contents',
            'type': 'text',
            'default': '',
            'description': 'Workflow code to be executed',
        },
        {
            'key': 'tags',
            'label': 'Tags',
            'type': 'text',
            'default': '',
            'description': 'A map of resource manager tags',
        },
        {
            'key': 'userEnvVars',
            'label': 'User Env Vars',
            'type': 'text',
            'default': '',
            'description': 'User-defined environment variables associated with this workflow revision',
        },
    ]

    # ── Ports ─────────────────────────────────────────────────────────────────
    inputs: ClassVar = [
        Port(
            'service_account',
            PortType.SERVICE_ACCOUNT,
            required=False,
            multi=False,
            multi_in=False,
        ),
    ]
    outputs: ClassVar = [
        Port(
            'calls',
            PortType.HTTP_TARGET,
            multi=True,
        ),
    ]

    # ── Edge wiring ───────────────────────────────────────────────────────────

    def resolve_edges(
        self,
        src_id:   str,
        tgt_id:   str,
        src_type: str,
        tgt_type: str,
        ctx:      dict[str, Any],
    ) -> bool:
if src_id != self.node_id:
    return False
if tgt_type == "CloudRunNode":
    ctx[self.node_id].setdefault("target_run_ids", []).append(tgt_id)
    return True
return False


    # ── DAG dependencies ──────────────────────────────────────────────────────

    def dag_deps(self, ctx: dict[str, Any]) -> list[str]:
my   = ctx.get(self.node_id, {})
deps = list(my.get("target_run_ids", []))
sa_id = my.get("service_account_id")
if sa_id:
    deps.append(sa_id)
return deps


    # ── Pulumi program ────────────────────────────────────────────────────────

    def pulumi_program(
        self,
        ctx:              dict[str, Any],
        project:          str,
        region:           str,
        all_nodes:        list[dict],
        deployed_outputs: dict[str, dict],
    ) -> Callable[[], None] | None:
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        sa_email  = deployed_outputs.get(
            ctx.get("service_account_id", ""), {}
        ).get("email", "")

        def program() -> None:
            resource_name = props.get("name") or _resource_name(node_dict)

            gcp.workflows.Workflow(
                self.node_id,
                name=resource_name,
                project=project,
                # ── add kwargs from props as needed ───────────────────────────
                # Extend this section or use pulumi_program_extra in your overlay
            )
            # pulumi.export("name", resource.name)

        return program

    # ── Post-deploy UI sync ───────────────────────────────────────────────────

    def live_outputs(
        self,
        pulumi_outputs: dict[str, Any],
        project:        str,
        region:         str,
    ) -> dict[str, Any]:
return {"name": pulumi_outputs.get("workflow_name", "")}


    # ── Log streaming ─────────────────────────────────────────────────────────

    def log_source(
        self,
        pulumi_outputs: dict[str, Any],
        project:        str,
        region:         str,
    ) -> LogSource | None:
name = pulumi_outputs.get("workflow_name", "")
if not name:
    return None
return LogSource(
    filter=(
        f'resource.type="workflows.googleapis.com/Workflow"'
        f' AND resource.labels.workflow_id="{name}"'
    ),
    project=project,
)


    # ── Extra methods (from overlay) ──────────────────────────────────────────
# YAML builder helpers — kept inline so the file is self-contained
    _STEP_YAML = (
        "  - {step_name}:\n"
        "      call: http.post\n"
        "      args:\n"
        "        url: {url}\n"
        "        auth:\n"
        "          type: OIDC\n"
        "      result: {step_name}_result\n"
    )
    _WF_YAML = "main:\n  steps:\n{steps}  - returnResult:\n      return: \"done\"\n"

    @staticmethod
    def _build_yaml(step_urls: list) -> str:
        steps = "".join(
            WorkflowNode._STEP_YAML.format(step_name=n, url=u)
            for n, u in step_urls
        )
        return WorkflowNode._WF_YAML.format(steps=steps)

    def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        my        = ctx.get(self.node_id, {})
        sa_email  = deployed_outputs.get(my.get("service_account_id", ""), {}).get("email", "")
        target_run_ids = my.get("target_run_ids", [])

        def program() -> None:
            source_yaml = (props.get("source_yaml") or "").strip()
            if not source_yaml:
                http_path  = props.get("http_path", "/")
                step_urls  = []
                for run_id in target_run_ids:
                    uri = deployed_outputs.get(run_id, {}).get("uri", "")
                    if uri:
                        step_name = re.sub(
                            r"[^a-z0-9_]", "_",
                            _node_name(all_nodes, run_id).lower()
                        )
                        step_urls.append((step_name, uri.rstrip("/") + http_path))
                source_yaml = (
                    WorkflowNode._build_yaml(step_urls) if step_urls
                    else 'main:\n  steps:\n  - returnResult:\n      return: "no targets wired"\n'
                )

            wf = gcp.workflows.Workflow(
                self.node_id,
                name=props.get("name") or _resource_name(node_dict),
                region=props.get("region", region),
                project=project,
                service_account=sa_email or None,
                source_contents=source_yaml,
            )
            pulumi.export("workflow_name", wf.name)
            pulumi.export("workflow_id",   wf.id)

        return program
