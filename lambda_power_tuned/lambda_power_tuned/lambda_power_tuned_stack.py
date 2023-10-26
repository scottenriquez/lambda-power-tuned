from aws_cdk import (aws_codebuild, aws_codecommit, aws_codepipeline,
					 aws_events, aws_events_targets, aws_iam, aws_s3, aws_sam,
					 RemovalPolicy, Stack)
from constructs import Construct
import uuid


class LambdaPowerTunedStack(Stack):
	def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
		super().__init__(scope, construct_id, **kwargs)
		# constants
		main_branch_name = 'main'
		terraform_version = '1.6.2'

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
				resources=[terraform_state_s3_bucket.arn_for_objects('*')]
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
							   aws_iam.ManagedPolicy.from_aws_managed_policy_name('AWSCodeCommitReadOnly'),
							   aws_iam.ManagedPolicy.from_aws_managed_policy_name('ReadOnlyAccess'),
							   terraform_s3_iam_policy
						   ])

		# source code repository for Lambda function and Terraform
		lambda_repository \
			= aws_codecommit.Repository(self, 'TargetLambdaFunctionRepository',
										repository_name='TargetLambdaFunctionRepository',
										code=aws_codecommit.Code.from_directory(
											'./lambda_power_tuned/terraform', main_branch_name))

		# pull request build and integration
		pull_request_codebuild_project \
			= aws_codebuild.Project(self, 'PullRequestCodeBuildProject',
									build_spec=aws_codebuild.BuildSpec.from_object({
										'version': '0.2',
										'phases': {
											'install': {
												'commands': [
													'git checkout $CODEBUILD_SOURCE_VERSION',
													'sudo yum -y install unzip',
													f'wget https://releases.hashicorp.com/terraform/${terraform_version}/terraform_${terraform_version}_linux_arm64.zip',
													f'unzip terraform_${terraform_version}_linux_arm64.zip',
													'sudo mv terraform /usr/local/bin/'
												]
											},
											'build': {
												'commands': [
													f'terraform init -backend-config="bucket=${terraform_state_s3_bucket.bucket_name}"',
													'terraform plan'
												]
											}
										}
									}),
									source=aws_codebuild.Source.code_commit(
										repository=lambda_repository),
									environment=aws_codebuild.BuildEnvironment(
										build_image=aws_codebuild.LinuxBuildImage.AMAZON_LINUX_2_ARM_3,
										privileged=True
									))

		pull_request_state_change_rule \
			= lambda_repository.on_pull_request_state_change('RepositoryOnPullRequestStateChange',
															 event_pattern=aws_events.EventPattern(
																 detail={
																	 'pullRequestStatus': ['Open']}),
															 target=aws_events_targets.CodeBuildProject(
																 project=pull_request_codebuild_project,
																 event=aws_events.RuleTargetInput.from_object(
																	 {
																		 'sourceVersion': aws_events.EventField.from_path(
																			 '$.detail.sourceReference')
																	 })
															 ))
