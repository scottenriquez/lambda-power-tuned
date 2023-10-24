from aws_cdk import (aws_codecommit, aws_s3, aws_sam, RemovalPolicy, Stack)
from constructs import Construct
import uuid

class LambdaPowerTunedStack(Stack):
	def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
		super().__init__(scope, construct_id, **kwargs)
		# Power Tuning
		power_tuning_tools_location = aws_sam.CfnApplication.ApplicationLocationProperty(
			application_id='arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning',
			semantic_version='4.3.2'
		)
		power_tuning_tools_parameters = {
			'lambdaResource': '*',
			'PowerValues': '128,256,512,1024,1536,3008'
		}
		power_tuning_tools_application = aws_sam.CfnApplication(self, 'LambdaPowerTuningTools',
			location=power_tuning_tools_location,
			parameters=power_tuning_tools_parameters)

		# CI/CD infrastructure and pipeline
		target_lambda_function_repository = aws_codecommit.Repository(self, 'TargetLambdaFunctionRepository',
			repository_name='TargetLambdaFunctionRepository',
			code=aws_codecommit.Code.from_directory('./lambda_power_tuned/terraform'))
		# the UUID ensures that the bucket name will be unique for this demo, but do not use in production
		# when the CDK application is deployed again, a new UUID will be generated and thus a new bucket
		terraform_state_s3_bucket_name = f'terraform-state-{uuid.uuid4()}'
		terraform_state_s3_bucket = aws_s3.Bucket(self, 'TerraformStateBucket',
			block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
			bucket_name=terraform_state_s3_bucket_name,
			removal_policy=RemovalPolicy.DESTROY)
