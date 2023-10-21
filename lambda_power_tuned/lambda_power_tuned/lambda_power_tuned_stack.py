from aws_cdk import (Stack, aws_sam as sam)
from constructs import Construct


class LambdaPowerTunedStack(Stack):
	def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
		super().__init__(scope, construct_id, **kwargs)
		power_tuning_tools_location = sam.CfnApplication.ApplicationLocationProperty(
			application_id='arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning',
			semantic_version='4.3.2'
		)
		power_tuning_tools_parameters = {
			'lambdaResource': '*',
			'PowerValues': '128,256,512,1024,1536,3008'
		}
		cfn_application = sam.CfnApplication(self, 'LambdaPowerTuningTools',
											 location=power_tuning_tools_location,
											 parameters=power_tuning_tools_parameters)
