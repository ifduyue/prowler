import threading
from typing import Optional

from botocore.client import ClientError
from pydantic import BaseModel

from prowler.lib.logger import logger
from prowler.lib.scan_filters.scan_filters import is_resource_filtered
from prowler.providers.aws.aws_provider import generate_regional_clients


################### ELBv2
class ELBv2:
    def __init__(self, audit_info):
        self.service = "elbv2"
        self.session = audit_info.audit_session
        self.audit_resources = audit_info.audit_resources
        self.regional_clients = generate_regional_clients(self.service, audit_info)
        self.loadbalancersv2 = []
        self.__threading_call__(self.__describe_load_balancers__)
        self.listeners = []
        self.__threading_call__(self.__describe_listeners__)
        self.__threading_call__(self.__describe_load_balancer_attributes__)
        self.__threading_call__(self.__describe_rules__)

    def __get_session__(self):
        return self.session

    def __threading_call__(self, call):
        threads = []
        for regional_client in self.regional_clients.values():
            threads.append(threading.Thread(target=call, args=(regional_client,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def __describe_load_balancers__(self, regional_client):
        logger.info("ELBv2 - Describing load balancers...")
        try:
            describe_elbv2_paginator = regional_client.get_paginator(
                "describe_load_balancers"
            )
            for page in describe_elbv2_paginator.paginate():
                for elbv2 in page["LoadBalancers"]:
                    if not self.audit_resources or (
                        is_resource_filtered(
                            elbv2["LoadBalancerArn"], self.audit_resources
                        )
                    ):
                        lb = LoadBalancerv2(
                            name=elbv2["LoadBalancerName"],
                            region=regional_client.region,
                            arn=elbv2["LoadBalancerArn"],
                            type=elbv2["Type"],
                            listeners=[],
                        )
                        if "DNSName" in elbv2:
                            lb.dns = elbv2["DNSName"]
                        if "Scheme" in elbv2:
                            lb.scheme = elbv2["Scheme"]
                        self.loadbalancersv2.append(lb)
        except Exception as error:
            logger.error(
                f"{regional_client.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )

    def __describe_listeners__(self, regional_client):
        logger.info("ELBv2 - Describing listeners...")
        try:
            for lb in self.loadbalancersv2:
                if lb.region == regional_client.region:
                    describe_elbv2_paginator = regional_client.get_paginator(
                        "describe_listeners"
                    )
                    for page in describe_elbv2_paginator.paginate(
                        LoadBalancerArn=lb.arn
                    ):
                        for listener in page["Listeners"]:
                            port = 0
                            if "Port" in listener:
                                port = listener["Port"]

                            listener_obj = Listenerv2(
                                region=regional_client.region,
                                arn=listener["ListenerArn"],
                                port=port,
                                ssl_policy=listener.get("SslPolicy"),
                                rules=[],
                            )
                            if "Protocol" in listener:
                                listener_obj.protocol = listener["Protocol"]

                            lb.listeners.append(listener_obj)

        except Exception as error:
            logger.error(
                f"{regional_client.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )

    def __describe_load_balancer_attributes__(self, regional_client):
        logger.info("ELBv2 - Describing attributes...")
        try:
            for lb in self.loadbalancersv2:
                if lb.region == regional_client.region:
                    for attribute in regional_client.describe_load_balancer_attributes(
                        LoadBalancerArn=lb.arn
                    )["Attributes"]:
                        if attribute["Key"] == "routing.http.desync_mitigation_mode":
                            lb.desync_mitigation_mode = attribute["Value"]
                        if attribute["Key"] == "deletion_protection.enabled":
                            lb.deletion_protection = attribute["Value"]
                        if attribute["Key"] == "access_logs.s3.enabled":
                            lb.access_logs = attribute["Value"]
                        if (
                            attribute["Key"]
                            == "routing.http.drop_invalid_header_fields.enabled"
                        ):
                            lb.drop_invalid_header_fields = attribute["Value"]
        except Exception as error:
            logger.error(
                f"{regional_client.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )

    def __describe_rules__(self, regional_client):
        logger.info("ELBv2 - Describing Rules...")
        try:
            for lb in self.loadbalancersv2:
                if lb.region == regional_client.region:
                    for listener in lb.listeners:
                        for rule in regional_client.describe_rules(
                            ListenerArn=listener.arn
                        )["Rules"]:
                            listener.rules.append(
                                ListenerRule(
                                    arn=rule["RuleArn"],
                                    actions=rule["Actions"],
                                    conditions=rule["Conditions"],
                                )
                            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ListenerNotFound":
                logger.warning(
                    f"{error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
                )
        except Exception as error:
            logger.error(
                f"{regional_client.region} -- {error.__class__.__name__}[{error.__traceback__.tb_lineno}]: {error}"
            )


class ListenerRule(BaseModel):
    arn: str
    actions: list[dict]
    conditions: list[dict]


class Listenerv2(BaseModel):
    arn: str
    region: str
    port: int
    protocol: Optional[str]
    ssl_policy: Optional[str]
    rules: list[ListenerRule]


class LoadBalancerv2(BaseModel):
    name: str
    arn: str
    region: str
    type: str
    access_logs: Optional[str]
    desync_mitigation_mode: Optional[str]
    deletion_protection: Optional[str]
    dns: Optional[str]
    drop_invalid_header_fields: Optional[str]
    listeners: list[Listenerv2]
    scheme: Optional[str]
