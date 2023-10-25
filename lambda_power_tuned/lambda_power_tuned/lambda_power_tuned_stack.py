from aws_cdk import (aws_codecommit, aws_iam, aws_s3, aws_sam, RemovalPolicy, Stack)
from constructs import Construct
import uuid


class LambdaPowerTunedStack(Stack):
	def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
		super().__init__(scope, construct_id, **kwargs)
		# Power Tuning application
		power_tuning_tools_location = aws_sam.CfnApplication.ApplicationLocationProperty(
			application_id='arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning',
			semantic_version='4.3.2'
		)
		power_tuning_tools_parameters = {
			'lambdaResource': '*',
			'PowerValues': '128,256,512,1024,1536,3008'
		}
		power_tuning_tools_application \
			= aws_sam.CfnApplication(self, 'LambdaPowerTuningTools',
									 location=power_tuning_tools_location,
									 parameters=power_tuning_tools_parameters)

		# Terraform state management
		# the UUID ensures that the bucket name will be unique for this demo, but do not use in production
		# when the CDK application is deployed again, a new UUID will be generated and thus a new bucket
		terraform_state_s3_bucket_name = f'terraform-state-{uuid.uuid4()}'
		terraform_state_s3_bucket \
			= aws_s3.Bucket(self, 'TerraformStateBucket',
							block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
							bucket_name=terraform_state_s3_bucket_name,
							removal_policy=RemovalPolicy.DESTROY)

		# IAM permissions
		terraform_s3_iam_policy \
			= aws_iam.ManagedPolicy(self, 'S3CodeBuildManagedPolicy', statements=[
			aws_iam.PolicyStatement(
				actions=['s3:GetObject', 's3:PutObject', 's3:DeleteObject'],
				resources=terraform_state_s3_bucket.arn_for_objects('*')
			),
			aws_iam.PolicyStatement(
				actions=['s3:ListBucket'],
				resources=['*']
			)
		])
		terraform_codebuild_iam_role \
			= aws_iam.Role(self, 'TerraformCodeBuildRole',
						   assumed_by=aws_iam.ServicePrincipal('codebuild.amazonaws.com'),
						   description='IAM role for CodeBuild to interact with S3',
						   managed_policies=[
							   aws_iam.ManagedPolicy.from_managed_policy_name('AWSCodeCommitReadOnly'),
							   aws_iam.ManagedPolicy.from_managed_policy_name('ReadOnlyAccess'),
							   terraform_s3_iam_policy
						   ])

		# CI/CD infrastructure and pipeline
		target_lambda_function_repository \
			= aws_codecommit.Repository(self, 'TargetLambdaFunctionRepository',
										repository_name='TargetLambdaFunctionRepository',
										code=aws_codecommit.Code.from_directory(
											'./lambda_power_tuned/terraform'))
