# AUTO-GENERATED — do not edit by hand.
# Source : pulumi schema (cloudrunv2.Job) + overlay
# Regen  : python codegen/schema_to_nodes.py --resources cloudrunv2.Job
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
class CloudRunJobNode(GCPNode):
    """Run-to-completion container job"""

    # ── UI metadata ───────────────────────────────────────────────────────────
    node_color:  ClassVar = "#818cf8"
    icon:        ClassVar = "cloudRunJob"
    category:    ClassVar = "Compute"
    description: ClassVar = "Run-to-completion container job"
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
            'key': 'image',
            'label': 'Container Image',
            'type': 'text',
            'default': '',
            'placeholder': 'gcr.io/project/image:tag',
        },
        {
            'key': 'memory',
            'label': 'Memory',
            'type': 'select',
            'options': ['256Mi', '512Mi', '1Gi', '2Gi', '4Gi', '8Gi'],
            'default': '512Mi',
        },
        {
            'key': 'cpu',
            'label': 'CPU',
            'type': 'select',
            'options': ['1', '2', '4', '8'],
            'default': '1',
        },
        {
            'key': 'parallelism',
            'label': 'Parallelism (concurrent tasks)',
            'type': 'number',
            'default': 1,
        },
        {
            'key': 'task_count',
            'label': 'Task Count',
            'type': 'number',
            'default': 1,
        },
        {
            'key': 'max_retries',
            'label': 'Max Retries per Task',
            'type': 'number',
            'default': 3,
        },
        {
            'key': 'timeout',
            'label': 'Task Timeout (seconds)',
            'type': 'number',
            'default': 600,
        },
        {
            'key': 'region',
            'label': 'Region',
            'type': 'select',
            'options': ['me-west1', 'us-central1', 'us-east1', 'europe-west1'],
            'default': 'me-west1',
        },
        {
            'key': 'vpc_network',
            'label': 'VPC Network (optional egress)',
            'type': 'text',
            'default': '',
            'placeholder': 'projects/HOST_PROJECT/global/networks/NETWORK',
        },
        {
            'key': 'vpc_subnetwork',
            'label': 'VPC Subnetwork (optional egress)',
            'type': 'text',
            'default': '',
            'placeholder': 'projects/HOST_PROJECT/regions/REGION/subnetworks/SUBNET',
        },
        {
            'key': 'binaryAuthorization',
            'label': 'Binary Authorization',
            'type': 'text',
            'default': '',
            'description': 'Settings for the Binary Authorization feature',
        },
        {
            'key': 'client',
            'label': 'Client',
            'type': 'text',
            'default': '',
            'description': 'Arbitrary identifier for the API client',
        },
        {
            'key': 'clientVersion',
            'label': 'Client Version',
            'type': 'text',
            'default': '',
            'description': 'Arbitrary version identifier for the API client',
        },
        {
            'key': 'deletionProtection',
            'label': 'Deletion Protection',
            'type': 'boolean',
            'default': '',
            'description': 'Whether Terraform will be prevented from destroying the job',
        },
        {
            'key': 'launchStage',
            'label': 'Launch Stage',
            'type': 'text',
            'default': '',
            'description': 'The launch stage as defined by [Google Cloud Platform Launch Stages](https://cloud',
        },
        {
            'key': 'location',
            'label': 'Location',
            'type': 'text',
            'default': '',
            'description': 'The location of the cloud run job\n',
        },
        {
            'key': 'runExecutionToken',
            'label': 'Run Execution Token',
            'type': 'text',
            'default': '',
            'description': '(Optional, Beta)\nA unique string used as a suffix creating a new execution upon job create or update',
        },
        {
            'key': 'startExecutionToken',
            'label': 'Start Execution Token',
            'type': 'text',
            'default': '',
            'description': '(Optional, Beta)\nA unique string used as a suffix creating a new execution upon job create or update',
        },
        {
            'key': 'template',
            'label': 'Template',
            'type': 'text',
            'default': '',
            'description': 'The template used to create executions for this Job',
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
        Port(
            'subnet',
            PortType.NETWORK,
            required=False,
            multi=False,
            multi_in=False,
        ),
        Port(
            'triggered_by',
            PortType.RUN_JOB,
            required=False,
            multi=True,
            multi_in=True,
        ),
        Port(
            'secret',
            PortType.SECRET,
            required=False,
            multi=True,
            multi_in=True,
        ),
    ]
    outputs: ClassVar = [
        Port(
            'publishes_to',
            PortType.TOPIC,
            multi=True,
        ),
        Port(
            'writes_to',
            PortType.STORAGE,
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
if src_id == self.node_id and src_type == "CloudRunJobNode":
    if tgt_type == "PubsubTopicNode":
        ctx[self.node_id].setdefault("publishes_to_topics", []).append(tgt_id)
        return True
    if tgt_type == "GcsBucketNode":
        ctx[tgt_id].setdefault("writer_ids", []).append(self.node_id)
        ctx[self.node_id].setdefault("bucket_ids", []).append(tgt_id)
        return True
return False


    # ── DAG dependencies ──────────────────────────────────────────────────────

    def dag_deps(self, ctx: dict[str, Any]) -> list[str]:
my   = ctx.get(self.node_id, {})
deps = list(my.get("publishes_to_topics", []))
deps += my.get("bucket_ids", [])
if my.get("subnetwork_id"):
    deps.append(my["subnetwork_id"])
if my.get("service_account_id"):
    deps.append(my["service_account_id"])
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

            gcp.cloudrunv2.Job(
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
return {"name": pulumi_outputs.get("job_name", "")}


    # ── Log streaming ─────────────────────────────────────────────────────────

    def log_source(
        self,
        pulumi_outputs: dict[str, Any],
        project:        str,
        region:         str,
    ) -> LogSource | None:
name = pulumi_outputs.get("job_name", "")
if not name:
    return None
return LogSource(
    filter=(
        f'resource.type="cloud_run_job"'
        f' AND resource.labels.job_name="{name}"'
        f' AND resource.labels.location="{region}"'
    ),
    project=project,
)


    # ── Extra methods (from overlay) ──────────────────────────────────────────
def pulumi_program(self, ctx, project, region, all_nodes, deployed_outputs):
        node_dict = ctx.get("node", {})
        props     = node_dict.get("props", {})
        my        = ctx.get(self.node_id, {})

        subnet_id       = my.get("subnetwork_id", "")
        subnet_outputs  = deployed_outputs.get(subnet_id, {})
        network_path    = subnet_outputs.get("network_path")    or props.get("vpc_network",    "")
        subnetwork_path = subnet_outputs.get("subnetwork_path") or props.get("vpc_subnetwork", "")
        sa_email        = deployed_outputs.get(my.get("service_account_id", ""), {}).get("email", "")

        topic_envs = [
            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                name="PUBSUB_TOPIC_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, tid).upper()),
                value=deployed_outputs.get(tid, {}).get("name", ""),
            )
            for tid in my.get("publishes_to_topics", [])
        ]
        bucket_envs = [
            gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
                name="GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()),
                value=deployed_outputs.get(bid, {}).get("name", ""),
            )
            for bid in my.get("bucket_ids", [])
        ]
        all_envs = topic_envs + bucket_envs

        def program() -> None:
            vpc_access = None
            if network_path and subnetwork_path:
                vpc_access = gcp.cloudrunv2.JobTemplateTemplateVpcAccessArgs(
                    egress="PRIVATE_RANGES_ONLY",
                    network_interfaces=[
                        gcp.cloudrunv2.JobTemplateTemplateVpcAccessNetworkInterfaceArgs(
                            network=network_path,
                            subnetwork=subnetwork_path,
                        )
                    ],
                )
            j = gcp.cloudrunv2.Job(
                self.node_id,
                name=props.get("name") or _resource_name(node_dict),
                location=props.get("region", region),
                project=project,
                deletion_protection=False,
                template=gcp.cloudrunv2.JobTemplateArgs(
                    parallelism=int(props.get("parallelism", 1)),
                    task_count=int(props.get("task_count", 1)),
                    template=gcp.cloudrunv2.JobTemplateTemplateArgs(
                        service_account=sa_email or None,
                        max_retries=int(props.get("max_retries", 3)),
                        timeout=f"{int(props.get('timeout', 600))}s",
                        containers=[
                            gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                                image=props.get("image", "gcr.io/cloudrun/hello"),
                                resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                                    limits={
                                        "memory": props.get("memory", "512Mi"),
                                        "cpu":    props.get("cpu", "1"),
                                    }
                                ),
                                envs=all_envs or None,
                            )
                        ],
                        vpc_access=vpc_access,
                    ),
                ),
            )
            pulumi.export("job_name", j.name)
            pulumi.export("job_id",   j.id)

        return program
