#!/usr/bin/env python3
import os

import aws_cdk as cdk

from lambda_power_tuned.lambda_power_tuned_stack import LambdaPowerTunedStack


app = cdk.App()
LambdaPowerTunedStack(app, 'LambdaPowerTunedStack')

app.synth()
