# AUTO-GENERATED — do not edit by hand.
# Source : pulumi schema (cloudrunv2.Service) + overlay
# Regen  : python codegen/schema_to_nodes.py --resources cloudrunv2.Service
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
class CloudRunNode(GCPNode):
    """Serverless container runtime"""

    # ── UI metadata ───────────────────────────────────────────────────────────
    node_color:  ClassVar = "#6366f1"
    icon:        ClassVar = "cloudRun"
    category:    ClassVar = "Compute"
    description: ClassVar = "Serverless container runtime"
    url_field:   ClassVar = 'service_url'

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
            'key': 'min_instances',
            'label': 'Min Instances',
            'type': 'number',
            'default': 0,
        },
        {
            'key': 'max_instances',
            'label': 'Max Instances',
            'type': 'number',
            'default': 10,
        },
        {
            'key': 'port',
            'label': 'Port',
            'type': 'number',
            'default': 8080,
        },
        {
            'key': 'region',
            'label': 'Region',
            'type': 'select',
            'options': ['me-west1', 'us-central1', 'us-east1', 'europe-west1'],
            'default': 'me-west1',
        },
        {
            'key': 'service_url',
            'label': 'Service URL',
            'type': 'text',
            'default': '',
            'placeholder': 'https://my-service.run.app',
        },
        {
            'key': 'vpc_network',
            'label': 'VPC Network (fallback)',
            'type': 'text',
            'default': '',
            'placeholder': 'projects/HOST_PROJECT/global/networks/NETWORK',
        },
        {
            'key': 'vpc_subnetwork',
            'label': 'VPC Subnetwork (fallback)',
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
            'key': 'buildConfig',
            'label': 'Build Config',
            'type': 'text',
            'default': '',
            'description': 'Configuration for building a Cloud Run function',
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
            'key': 'customAudiences',
            'label': 'Custom Audiences',
            'type': 'text',
            'default': '',
            'description': 'One or more custom audiences that you want this service to support',
        },
        {
            'key': 'defaultUriDisabled',
            'label': 'Default Uri Disabled',
            'type': 'boolean',
            'default': '',
            'description': 'Disables public resolution of the default URI of this service',
        },
        {
            'key': 'deletionProtection',
            'label': 'Deletion Protection',
            'type': 'boolean',
            'default': '',
            'description': 'Whether Terraform will be prevented from destroying the service',
        },
        {
            'key': 'description',
            'label': 'Description',
            'type': 'text',
            'default': '',
            'description': 'User-provided description of the Service',
        },
        {
            'key': 'iapEnabled',
            'label': 'Iap Enabled',
            'type': 'boolean',
            'default': '',
            'description': 'Used to enable/disable IAP for the cloud-run service',
        },
        {
            'key': 'ingress',
            'label': 'Ingress',
            'type': 'text',
            'default': '',
            'description': 'Provides the ingress settings for this Service',
        },
        {
            'key': 'invokerIamDisabled',
            'label': 'Invoker Iam Disabled',
            'type': 'boolean',
            'default': '',
            'description': 'Disables IAM permission check for run',
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
            'description': 'The location of the cloud run service\n',
        },
        {
            'key': 'multiRegionSettings',
            'label': 'Multi Region Settings',
            'type': 'text',
            'default': '',
            'description': 'Settings for creating a Multi-Region Service',
        },
        {
            'key': 'scaling',
            'label': 'Scaling',
            'type': 'text',
            'default': '',
            'description': 'Scaling settings that apply to the whole service\nStructure is documented below',
        },
        {
            'key': 'template',
            'label': 'Template',
            'type': 'text',
            'default': '',
            'description': 'The template used to create revisions for this Service',
        },
        {
            'key': 'traffics',
            'label': 'Traffics',
            'type': 'text',
            'default': '',
            'description': 'Specifies how to distribute traffic over a collection of Revisions belonging to the Service',
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
            'http_callers',
            PortType.HTTP_TARGET,
            required=False,
            multi=True,
            multi_in=True,
        ),
        Port(
            'task_queue',
            PortType.TASK_QUEUE,
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
        Port(
            'MESSAGE',
            PortType.MESSAGE,
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
if src_id == self.node_id and src_type == "CloudRunNode":
    if tgt_type == "PubsubTopicNode":
        ctx[self.node_id].setdefault("publishes_to_topics", []).append(tgt_id)
        return True
    if tgt_type == "GcsBucketNode":
        ctx[tgt_id].setdefault("writer_ids", []).append(self.node_id)
        return True
return False


    # ── DAG dependencies ──────────────────────────────────────────────────────

    def dag_deps(self, ctx: dict[str, Any]) -> list[str]:
my  = ctx.get(self.node_id, {})
deps = list(my.get("publishes_to_topics", []))
deps += my.get("bucket_ids", [])
deps += my.get("task_queue_ids", [])
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
my = ctx.get(self.node_id, {})

# VPC paths
subnet_id       = my.get("subnetwork_id", "")
subnet_outputs  = deployed_outputs.get(subnet_id, {})
network_path    = subnet_outputs.get("network_path")    or props.get("vpc_network",    "")
subnetwork_path = subnet_outputs.get("subnetwork_path") or props.get("vpc_subnetwork", "")

if not network_path or not subnetwork_path:
    logger.warning(
        "CloudRunNode %s: no VPC resolved — connect SubnetworkNode or fill fallback props",
        self.node_id,
    )

# Env vars from wired nodes
topic_envs = [
    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
        name="PUBSUB_TOPIC_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, tid).upper()),
        value=deployed_outputs.get(tid, {}).get("name", ""),
    )
    for tid in my.get("publishes_to_topics", [])
]
bucket_envs = [
    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
        name="GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()),
        value=deployed_outputs.get(bid, {}).get("name", ""),
    )
    for bid in my.get("bucket_ids", [])
]
queue_envs = [
    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
        name="CLOUD_TASKS_QUEUE_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, qid).upper()),
        value=deployed_outputs.get(qid, {}).get("queue_name", ""),
    )
    for qid in my.get("task_queue_ids", [])
]
sub_envs = [
    gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
        name="PUBSUB_SUBSCRIPTION_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, sid).upper()),
        value=_resource_name(next((n for n in all_nodes if n["id"] == sid), {})),
    )
    for sid in my.get("receives_from_subs", [])
]
all_envs = topic_envs + bucket_envs + queue_envs + sub_envs

        def program() -> None:
            resource_name = props.get("name") or _resource_name(node_dict)

            gcp.cloudrunv2.Service(
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
return {"service_url": pulumi_outputs.get("uri", "")}


    # ── Log streaming ─────────────────────────────────────────────────────────

    def log_source(
        self,
        pulumi_outputs: dict[str, Any],
        project:        str,
        region:         str,
    ) -> LogSource | None:
name = pulumi_outputs.get("name", "")
if not name:
    return None
return LogSource(
    filter=(
        f'resource.type="cloud_run_revision"'
        f' AND resource.labels.service_name="{name}"'
        f' AND resource.labels.location="{region}"'
    ),
    project=project,
)


    # ── Extra methods (from overlay) ──────────────────────────────────────────
# override the generated program() to use the full Cloud Run API surface
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
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="PUBSUB_TOPIC_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, tid).upper()),
                value=deployed_outputs.get(tid, {}).get("name", ""),
            )
            for tid in my.get("publishes_to_topics", [])
        ]
        bucket_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="GCS_BUCKET_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, bid).upper()),
                value=deployed_outputs.get(bid, {}).get("name", ""),
            )
            for bid in my.get("bucket_ids", [])
        ]
        queue_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="CLOUD_TASKS_QUEUE_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, qid).upper()),
                value=deployed_outputs.get(qid, {}).get("queue_name", ""),
            )
            for qid in my.get("task_queue_ids", [])
        ]
        sub_envs = [
            gcp.cloudrunv2.ServiceTemplateContainerEnvArgs(
                name="PUBSUB_SUBSCRIPTION_" + re.sub(r"[^A-Z0-9]", "_", _node_name(all_nodes, sid).upper()),
                value=_resource_name(next((n for n in all_nodes if n["id"] == sid), {})),
            )
            for sid in my.get("receives_from_subs", [])
        ]
        all_envs = topic_envs + bucket_envs + queue_envs + sub_envs

        def program() -> None:
            vpc_access = None
            if network_path and subnetwork_path:
                vpc_access = gcp.cloudrunv2.ServiceTemplateVpcAccessArgs(
                    egress="PRIVATE_RANGES_ONLY",
                    network_interfaces=[
                        gcp.cloudrunv2.ServiceTemplateVpcAccessNetworkInterfaceArgs(
                            network=network_path,
                            subnetwork=subnetwork_path,
                        )
                    ],
                )
            svc = gcp.cloudrunv2.Service(
                self.node_id,
                name=props.get("name") or _resource_name(node_dict),
                location=region,
                project=project,
                deletion_protection=False,
                ingress="INGRESS_TRAFFIC_INTERNAL_ONLY",
                template=gcp.cloudrunv2.ServiceTemplateArgs(
                    service_account=sa_email or None,
                    containers=[gcp.cloudrunv2.ServiceTemplateContainerArgs(
                        image=props.get("image", "gcr.io/cloudrun/hello"),
                        envs=all_envs or None,
                    )],
                    vpc_access=vpc_access,
                ),
            )
            pulumi.export("uri",  svc.uri)
            pulumi.export("name", svc.name)
            pulumi.export("id",   svc.id)

        return program
