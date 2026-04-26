"""
terraform_gen/generators/pubsub.py
====================================
Generates Terraform HCL for:
  - PubsubTopicNode                     → google_pubsub_topic
  - PubsubPullSubscriptionNode          → google_pubsub_subscription (pull)
  - PubsubPushSubscriptionNode          → google_pubsub_subscription (push)
  - PubsubBigQuerySubscriptionNode      → google_pubsub_subscription (bigquery)
  - PubsubCloudStorageSubscriptionNode  → google_pubsub_subscription (cloud_storage)
"""
from __future__ import annotations

from .base import BaseGenerator, GeneratorResult, TFBlock


class PubsubTopicGenerator(BaseGenerator):
    handled_types = {"PubsubTopicNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        body: dict = {
            "name":    name,
            "project": "var.project_id",
        }
        if props.get("message_retention_duration"):
            body["message_retention_duration"] = props["message_retention_duration"]
        if props.get("kms_key_name"):
            body["kms_key_name"] = props["kms_key_name"]

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_pubsub_topic", tf_id],
            body=body,
            comment=f"Pub/Sub Topic: {node.get('label', name)}",
        ))

        result.outputs.append(TFBlock(
            block_type="output",
            labels=[f"{tf_id}_name"],
            body={
                "description": f"Pub/Sub topic name: {name}",
                "value":       f"${{google_pubsub_topic.{tf_id}.name}}",
            },
        ))
        return result


class PubsubPullSubscriptionGenerator(BaseGenerator):
    handled_types = {"PubsubPullSubscriptionNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        topic_id = ctx.get("topic_id", "")
        if topic_id:
            topic_node = self.node_by_id(all_nodes, topic_id)
            topic_ref  = f"${{google_pubsub_topic.{self.tf_name(topic_node)}.id}}"
        else:
            topic_ref = ""

        body: dict = {
            "name":                name,
            "project":             "var.project_id",
            "topic":               topic_ref,
            "ack_deadline_seconds": int(props.get("ack_deadline_seconds", 20)),
        }
        if props.get("filter"):
            body["filter"] = props["filter"]
        if props.get("enable_message_ordering"):
            body["enable_message_ordering"] = True
        if props.get("enable_exactly_once_delivery"):
            body["enable_exactly_once_delivery"] = True
        if props.get("dead_letter_topic"):
            body["dead_letter_policy"] = {"dead_letter_topic": props["dead_letter_topic"]}

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_pubsub_subscription", tf_id],
            body=body,
            comment=f"Pub/Sub Pull Subscription: {node.get('label', name)}",
        ))
        return result


class PubsubPushSubscriptionGenerator(BaseGenerator):
    handled_types = {"PubsubPushSubscriptionNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        topic_id = ctx.get("topic_id", "")
        topic_ref = ""
        if topic_id:
            topic_node = self.node_by_id(all_nodes, topic_id)
            topic_ref  = f"${{google_pubsub_topic.{self.tf_name(topic_node)}.id}}"

        # Try to auto-resolve push endpoint from wired Cloud Run
        push_endpoint = props.get("push_endpoint", "")
        for tid in ctx.get("push_target_ids", []):
            cr_node = self.node_by_id(all_nodes, tid)
            if cr_node:
                push_endpoint = f"${{google_cloud_run_v2_service.{self.tf_name(cr_node)}.uri}}"
                break

        push_config: dict = {"push_endpoint": push_endpoint}
        if props.get("oidc_service_account_email"):
            push_config["oidc_token"] = {
                "service_account_email": props["oidc_service_account_email"],
                "audience":              props.get("audience", ""),
            }

        body = {
            "name":                name,
            "project":             "var.project_id",
            "topic":               topic_ref,
            "ack_deadline_seconds": int(props.get("ack_deadline_seconds", 20)),
            "push_config":         push_config,
        }
        if props.get("filter"):
            body["filter"] = props["filter"]

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_pubsub_subscription", tf_id],
            body=body,
            comment=f"Pub/Sub Push Subscription: {node.get('label', name)}",
        ))
        return result


class PubsubBigQuerySubscriptionGenerator(BaseGenerator):
    handled_types = {"PubsubBigQuerySubscriptionNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        topic_id = ctx.get("topic_id", "")
        topic_ref = f"${{google_pubsub_topic.{self.tf_name(self.node_by_id(all_nodes, topic_id))}.id}}" if topic_id else ""

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_pubsub_subscription", tf_id],
            body={
                "name":    name,
                "project": "var.project_id",
                "topic":   topic_ref,
                "bigquery_config": {
                    "table":            props.get("table", ""),
                    "use_topic_schema": bool(props.get("use_topic_schema", False)),
                    "write_metadata":   bool(props.get("write_metadata", False)),
                },
            },
            comment=f"Pub/Sub BigQuery Subscription: {node.get('label', name)}",
        ))
        return result


class PubsubCloudStorageSubscriptionGenerator(BaseGenerator):
    handled_types = {"PubsubCloudStorageSubscriptionNode"}

    def generate(self, node, ctx, project, region, all_nodes, edges):
        result = GeneratorResult()
        props  = node.get("props", {})
        name   = self.resource_name(node)
        tf_id  = self.tf_name(node)

        topic_id = ctx.get("topic_id", "")
        topic_ref = f"${{google_pubsub_topic.{self.tf_name(self.node_by_id(all_nodes, topic_id))}.id}}" if topic_id else ""

        cs_config: dict = {"bucket": props.get("bucket", "")}
        if props.get("filename_prefix"):
            cs_config["filename_prefix"] = props["filename_prefix"]
        output_format = props.get("output_format", "text")
        if output_format == "avro":
            cs_config["avro_config"] = {"write_metadata": True}

        result.resources.append(TFBlock(
            block_type="resource",
            labels=["google_pubsub_subscription", tf_id],
            body={
                "name":                 name,
                "project":              "var.project_id",
                "topic":                topic_ref,
                "cloud_storage_config": cs_config,
            },
            comment=f"Pub/Sub Cloud Storage Subscription: {node.get('label', name)}",
        ))
        return result
