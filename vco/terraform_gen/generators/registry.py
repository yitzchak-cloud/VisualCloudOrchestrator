"""
terraform_gen/generators/registry.py
======================================
Auto-discovers and registers all TF generators.
Returns a dict mapping node_type → generator instance.
"""
from __future__ import annotations

from .base import BaseGenerator
from .cloud_run import CloudRunGenerator, CloudRunJobGenerator
from .pubsub import (
    PubsubTopicGenerator,
    PubsubPullSubscriptionGenerator,
    PubsubPushSubscriptionGenerator,
    PubsubBigQuerySubscriptionGenerator,
    PubsubCloudStorageSubscriptionGenerator,
)
from .gcp_resources import (
    GcsBucketGenerator,
    VpcNetworkGenerator,
    SubnetworkGenerator,
    ServiceAccountGenerator,
    CloudSchedulerGenerator,
    CloudTasksQueueGenerator,
    EventarcTriggerGenerator,
    WorkflowGenerator,
)

# All generator classes
_GENERATOR_CLASSES: list[type[BaseGenerator]] = [
    CloudRunGenerator,
    CloudRunJobGenerator,
    PubsubTopicGenerator,
    PubsubPullSubscriptionGenerator,
    PubsubPushSubscriptionGenerator,
    PubsubBigQuerySubscriptionGenerator,
    PubsubCloudStorageSubscriptionGenerator,
    GcsBucketGenerator,
    VpcNetworkGenerator,
    SubnetworkGenerator,
    ServiceAccountGenerator,
    CloudSchedulerGenerator,
    CloudTasksQueueGenerator,
    EventarcTriggerGenerator,
    WorkflowGenerator,
]

# Build registry: node_type → generator instance
TF_GENERATOR_REGISTRY: dict[str, BaseGenerator] = {}
for _cls in _GENERATOR_CLASSES:
    _inst = _cls()
    for _node_type in _cls.handled_types:
        TF_GENERATOR_REGISTRY[_node_type] = _inst
