"""D-0004 budget guard. Deployed (and verified) before anything that can launch EC2.

  * Budget `riversight-cap`: $100 of gross cost (credits excluded, so it measures what the card could be
    charged), cumulative from 2026-10-01 (annual period, so the October and November spend add up instead
    of resetting on Nov 1). Email alerts at 25/50/75/90 % actual and 100 % forecasted.
  * Stop action: the same budget notifies the `riversight-stop` SNS topic at `stop_at_pct` (100 % since ANSWER 0013) actual; a Lambda stops
    every running instance tagged Project=riversight (reversible; nothing is terminated).

A CloudWatch billing alarm (D-0004's backup) needs the EstimatedCharges metric, which exists only in
us-east-1; the new AWS experience allows only CloudWatch Logs and WAF there, so the forecasted-spend budget
notification is the backup instead (recorded in docs/status/W1.md).
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack, Tags
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

LAMBDA_DIR = Path(__file__).resolve().parents[1] / "lambda"


class GuardStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, email: str, budget_usd: float, stop_pct: float, **kw):
        super().__init__(scope, cid, **kw)
        Tags.of(self).add("Project", "riversight")

        stop_topic = sns.Topic(self, "StopTopic", topic_name="riversight-stop")
        stop_topic.add_to_resource_policy(iam.PolicyStatement(
            actions=["sns:Publish"], principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
            resources=[stop_topic.topic_arn],
            conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        stop_topic.add_subscription(subs.EmailSubscription(email))

        fn = lambda_.Function(
            self, "StopEc2", function_name="riversight-budget-stop-ec2",
            runtime=lambda_.Runtime.PYTHON_3_14, architecture=lambda_.Architecture.ARM_64,
            handler="index.handler", code=lambda_.Code.from_asset(str(LAMBDA_DIR / "stop_ec2")),
            timeout=Duration.seconds(60), memory_size=128,
            log_group=logs.LogGroup(self, "StopEc2Logs", retention=logs.RetentionDays.ONE_MONTH))
        fn.add_to_role_policy(iam.PolicyStatement(actions=["ec2:DescribeInstances"], resources=["*"]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ec2:StopInstances"], resources=["*"],
            conditions={"StringEquals": {"aws:ResourceTag/Project": "riversight"}}))
        stop_topic.add_subscription(subs.LambdaSubscription(fn))

        def email_note(pct, kind="ACTUAL"):
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    comparison_operator="GREATER_THAN", notification_type=kind, threshold=pct,
                    threshold_type="PERCENTAGE"),
                subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=email)])

        notes = [email_note(p) for p in (25, 50, 75)] + [email_note(100, "FORECASTED")]
        notes.append(budgets.CfnBudget.NotificationWithSubscribersProperty(
            notification=budgets.CfnBudget.NotificationProperty(
                comparison_operator="GREATER_THAN", notification_type="ACTUAL", threshold=stop_pct,
                threshold_type="PERCENTAGE"),
            subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=email),
                         budgets.CfnBudget.SubscriberProperty(subscription_type="SNS", address=stop_topic.topic_arn)]))
        budget = budgets.CfnBudget(
            self, "Budget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="riversight-cap", budget_type="COST", time_unit="ANNUALLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=budget_usd, unit="USD"),
                time_period=budgets.CfnBudget.TimePeriodProperty(start="1790812800", end="1798675200"),
                cost_types=budgets.CfnBudget.CostTypesProperty(
                    include_credit=False, include_refund=False, include_tax=True, include_support=True,
                    include_other_subscription=True, include_subscription=True, include_upfront=True,
                    include_recurring=True, include_discount=True, use_blended=False, use_amortized=False)),
            notifications_with_subscribers=notes)
        budget.node.add_dependency(stop_topic)

        self.stop_topic = stop_topic
        CfnOutput(self, "BudgetName", value="riversight-cap")
        CfnOutput(self, "StopTopicArn", value=stop_topic.topic_arn)
        CfnOutput(self, "StopFunctionArn", value=fn.function_arn)
