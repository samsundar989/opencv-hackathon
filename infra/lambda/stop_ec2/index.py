"""D-0004 budget guard: stop every running EC2 instance tagged Project=riversight.

Triggered by the riversight-stop SNS topic, which the $100 budget notifies at 90 % of actual spend.
Stopping (not terminating) is reversible: EBS volumes and the instance survive; Samuel restarts by hand.
"""
import json
import os

import boto3


def handler(event, context):
    ec2 = boto3.client("ec2", region_name=os.environ.get("AWS_REGION"))
    r = ec2.describe_instances(Filters=[{"Name": "tag:Project", "Values": ["riversight"]},
                                        {"Name": "instance-state-name", "Values": ["pending", "running"]}])
    ids = [i["InstanceId"] for res in r["Reservations"] for i in res["Instances"]]
    if ids and os.environ.get("DRY_RUN") != "1":
        ec2.stop_instances(InstanceIds=ids)
    msg = {"stopped": ids, "dry_run": os.environ.get("DRY_RUN") == "1",
           "trigger": [rec.get("Sns", {}).get("Subject") for rec in event.get("Records", [])]}
    print(json.dumps(msg))
    return msg
