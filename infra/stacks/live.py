"""RiverSight live stack (SPRINT W1 step 3), us-east-2 only.

  S3 bucket (private)  ── site/   static dashboard (CloudFront default behaviour, origin path /site)
                       ── live/   readings, overlays, index, agent log, approvals, proof.json (CloudFront /live/*)
                       ── models/ site bundles, deploy/ worker tarball (never served)
  CloudFront (OAC to S3; /api/* → approvals Lambda Function URL)
  Graviton worker (EC2, IMDSv2, no SSH, SSM only) running `riversight.live.cycle --s3` from a systemd timer
  SNS alert topic (email to Samuel), CloudWatch dashboard + alarms (no cycle in 75 min, cycle errors)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cwa
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

INFRA = Path(__file__).resolve().parents[1]
NAMESPACE = "RiverSight"


class LiveStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, email: str, worker_ami: str, instance_type: str,
                 bedrock_profile: str, approval_token_sha256: str = "", cool_ami_id: str = "",
                 origin_secret: str = "", **kw):
        super().__init__(scope, cid, **kw)
        Tags.of(self).add("Project", "riversight")

        bucket = s3.Bucket(
            self, "Bucket", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
            encryption=s3.BucketEncryption.S3_MANAGED, versioned=False,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[s3.LifecycleRule(prefix="live/frames/", expiration=Duration.days(30))])

        alerts = sns.Topic(self, "Alerts", topic_name="riversight-alerts")
        alerts.add_subscription(subs.EmailSubscription(email))

        # ---- approvals API --------------------------------------------------------------------------
        api = lambda_.Function(
            self, "Approvals", function_name="riversight-approvals",
            runtime=lambda_.Runtime.PYTHON_3_14, architecture=lambda_.Architecture.ARM_64,
            handler="index.handler", code=lambda_.Code.from_asset(str(INFRA / "lambda" / "approvals")),
            timeout=Duration.seconds(15), memory_size=256,
            environment={"BUCKET": bucket.bucket_name, "APPROVAL_TOKEN_SHA256": approval_token_sha256,
                         "ORIGIN_SECRET_SHA256": hashlib.sha256(origin_secret.encode()).hexdigest() if origin_secret else ""},
            log_group=logs.LogGroup(self, "ApprovalsLogs", retention=logs.RetentionDays.ONE_MONTH))
        bucket.grant_read(api, "live/approvals/*")
        bucket.grant_put(api, "live/approvals/*")
        bucket.grant_read_write(api, "live/agent/*")
        api.add_to_role_policy(iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket.bucket_arn],
                                                   conditions={"StringLike": {"s3:prefix": ["live/approvals/*"]}}))
        api_url = api.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)

        # ---- CloudFront -----------------------------------------------------------------------------
        live_cache = cf.CachePolicy(
            self, "LiveCache", default_ttl=Duration.seconds(60), min_ttl=Duration.seconds(0),
            max_ttl=Duration.minutes(5), enable_accept_encoding_gzip=True, enable_accept_encoding_brotli=True)
        site_origin = origins.S3BucketOrigin.with_origin_access_control(bucket, origin_path="/site")
        live_origin = origins.S3BucketOrigin.with_origin_access_control(bucket)
        dist = cf.Distribution(
            self, "Site", comment="RiverSight live dashboard", default_root_object="index.html",
            price_class=cf.PriceClass.PRICE_CLASS_100, http_version=cf.HttpVersion.HTTP2_AND_3,
            default_behavior=cf.BehaviorOptions(
                origin=site_origin, viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=live_cache, compress=True),
            additional_behaviors={
                "/live/*": cf.BehaviorOptions(
                    origin=live_origin, viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=live_cache, compress=True),
                "/api/*": cf.BehaviorOptions(
                    origin=origins.FunctionUrlOrigin(api_url, custom_headers={"x-origin-verify": origin_secret}
                                                     if origin_secret else None),
                    viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cf.AllowedMethods.ALLOW_ALL, cache_policy=cf.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER),
            })

        # ---- worker ---------------------------------------------------------------------------------
        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=0,
                      subnet_configuration=[ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)])
        sg = ec2.SecurityGroup(self, "WorkerSg", vpc=vpc, allow_all_outbound=True,
                               description="RiverSight worker: no inbound (SSM only)")
        role = iam.Role(self, "WorkerRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                        managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")])
        bucket.grant_read_write(role, "live/*")
        bucket.grant_read(role, "models/*")
        bucket.grant_read(role, "deploy/*")
        role.add_to_policy(iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket.bucket_arn]))
        role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse",
                     "bedrock:ConverseStream"],
            # Anthropic Claude only: the US cross-region profiles the agent uses (Haiku 4.5 / Sonnet 4.6 today,
            # 5.5 once its agreement is active) and the foundation models those profiles route to in us-* Regions
            resources=[f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{bedrock_profile}",
                       "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"]))
        alerts.grant_publish(role)
        role.add_to_policy(iam.PolicyStatement(          # spend on /proof: read the guard budget only
            actions=["budgets:ViewBudget"],
            resources=[f"arn:aws:budgets::{self.account}:budget/riversight-cap"]))
        role.add_to_policy(iam.PolicyStatement(actions=["cloudwatch:PutMetricData"], resources=["*"],
                                               conditions={"StringEquals": {"cloudwatch:namespace": NAMESPACE}}))

        if worker_ami == "cool":
            machine = ec2.MachineImage.generic_linux({self.region: cool_ami_id})
        else:
            machine = ec2.MachineImage.from_ssm_parameter(
                "/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id")
        user_data = ec2.UserData.for_linux()
        script = (INFRA / "worker" / "bootstrap.sh").read_bytes().decode("utf-8").replace("\r\n", "\n")
        user_data.add_commands(script.replace("__BUCKET__", bucket.bucket_name)
                               .replace("__REGION__", self.region)
                               .replace("__ALERTS__", alerts.topic_arn)
                               .replace("__SITE_URL__", f"https://{dist.distribution_domain_name}")
                               .replace("__AMI_KIND__", worker_ami))
        worker = ec2.Instance(
            self, "Worker", instance_name="riversight-worker", vpc=vpc, security_group=sg, role=role,
            instance_type=ec2.InstanceType(instance_type), machine_image=machine, user_data=user_data,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC), associate_public_ip_address=True,
            require_imdsv2=True, user_data_causes_replacement=True,   # cloud-init runs user data on first boot only
            # both images boot from /dev/sda1; the COOL AMI's snapshot is 80 GB, so its root volume cannot be smaller
            block_devices=[ec2.BlockDevice(device_name="/dev/sda1",
                                           volume=ec2.BlockDeviceVolume.ebs(80 if worker_ami == "cool" else 20,
                                                                            volume_type=ec2.EbsDeviceVolumeType.GP3,
                                                                            encrypted=True))])

        # ---- observability --------------------------------------------------------------------------
        def metric(name, stat="Sum", period=Duration.minutes(30)):
            return cw.Metric(namespace=NAMESPACE, metric_name=name, statistic=stat, period=period)

        no_cycle = cw.Alarm(self, "NoCycle", alarm_name="riversight-no-cycle-75min",
                            metric=metric("CycleCompleted", period=Duration.minutes(75)), threshold=1,
                            comparison_operator=cw.ComparisonOperator.LESS_THAN_THRESHOLD, evaluation_periods=1,
                            treat_missing_data=cw.TreatMissingData.BREACHING)
        errors = cw.Alarm(self, "CycleErrors", alarm_name="riversight-cycle-errors",
                          metric=metric("SiteErrors", period=Duration.hours(1)), threshold=10,
                          comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                          evaluation_periods=1, treat_missing_data=cw.TreatMissingData.NOT_BREACHING)
        for a in (no_cycle, errors):
            a.add_alarm_action(cwa.SnsAction(alerts))
        dash = cw.Dashboard(self, "Dash", dashboard_name="riversight")
        dash.add_widgets(
            cw.GraphWidget(title="Cycle time (s)", left=[metric("CycleSeconds", "Maximum")]),
            cw.GraphWidget(title="Sites OK / flagged / errors",
                           left=[metric("SitesOk", "Maximum"), metric("SitesFlagged", "Maximum"),
                                 metric("SiteErrors")]),
            cw.GraphWidget(title="Agent decisions (LLM / rules) and tokens",
                           left=[metric("AgentLLM"), metric("AgentRules")], right=[metric("AgentTokens")]),
            cw.AlarmStatusWidget(title="Alarms", alarms=[no_cycle, errors]))

        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "SiteUrl", value=f"https://{dist.distribution_domain_name}")
        CfnOutput(self, "DistributionId", value=dist.distribution_id)
        CfnOutput(self, "AlertTopicArn", value=alerts.topic_arn)
        CfnOutput(self, "WorkerInstanceId", value=worker.instance_id)
        CfnOutput(self, "ApprovalsFunctionUrl", value=api_url.url)
