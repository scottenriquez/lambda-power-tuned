from aws_cdk import (aws_codebuild, aws_codecommit, aws_codepipeline, aws_codepipeline_actions,
					 aws_events, aws_events_targets, aws_iam, aws_s3, aws_sam,
					 RemovalPolicy, Stack)
from constructs import Construct
import uuid


class LambdaPowerTunedStack(Stack):
	def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
		super().__init__(scope, construct_id, **kwargs)
		# constants
		main_branch_name = 'main'
		terraform_version = '1.6.3'

		# Power Tuning application
		power_tuning_tools_location = aws_sam.CfnApplication.ApplicationLocationProperty(
			application_id='arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning',
			semantic_version='4.3.3'
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
							auto_delete_objects=True,
							block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
							bucket_name=terraform_state_s3_bucket_name,
							removal_policy=RemovalPolicy.DESTROY)

		# IAM permissions
		terraform_build_s3_iam_policy \
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
		terraform_plan_codebuild_iam_role \
			= aws_iam.Role(self, 'TerraformPlanCodeBuildRole',
						   assumed_by=aws_iam.ServicePrincipal('codebuild.amazonaws.com'),
						   description='IAM role for CodeBuild to interact with S3 for a Terraform plan',
						   managed_policies=[
							   aws_iam.ManagedPolicy.from_aws_managed_policy_name('AWSCodeCommitReadOnly'),
							   aws_iam.ManagedPolicy.from_aws_managed_policy_name('ReadOnlyAccess'),
							   terraform_build_s3_iam_policy
						   ])
		terraform_apply_codebuild_iam_role \
			= aws_iam.Role(self, 'TerraformApplyCodeBuildRole',
						   assumed_by=aws_iam.ServicePrincipal('codebuild.amazonaws.com'),
						   description='IAM role for CodeBuild to deploy resources via Terraform',
						   managed_policies=[
							   aws_iam.ManagedPolicy.from_aws_managed_policy_name('AdministratorAccess')
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
													'yum -y install unzip util-linux jq',
													f'wget https://releases.hashicorp.com/terraform/{terraform_version}/terraform_{terraform_version}_linux_arm64.zip',
													f'unzip terraform_{terraform_version}_linux_arm64.zip',
													'mv terraform /usr/local/bin/',
													'export BUILD_UUID=$(uuidgen)'
												]
											},
											'build': {
												'commands': [
													'aws codecommit post-comment-for-pull-request --repository-name $REPOSITORY_NAME --pull-request-id $PULL_REQUEST_ID --content \"The pull request CodeBuild project has been triggered. See the [logs for more details]($CODEBUILD_BUILD_URL).\" --before-commit-id $SOURCE_COMMIT --after-commit-id $DESTINATION_COMMIT',
													# create plan against the production function
													f'terraform init -backend-config="bucket={terraform_state_s3_bucket.bucket_name}"',
													'terraform plan -out tfplan-pr-$BUILD_UUID.out',
													'terraform show -json tfplan-pr-$BUILD_UUID.out > plan-$BUILD_UUID.json',
													'echo "\`\`\`json\n$(cat plan-$BUILD_UUID.json | jq \'.resource_changes\')\n\`\`\`" > plan-formatted-$BUILD_UUID.json',
													# write plan to the pull request comments
													'aws codecommit post-comment-for-pull-request --repository-name $REPOSITORY_NAME --pull-request-id $PULL_REQUEST_ID --content \"Terraform resource changes:\n$(cat plan-formatted-$BUILD_UUID.json | head -c 10000)\" --before-commit-id $SOURCE_COMMIT --after-commit-id $DESTINATION_COMMIT',
													# create a new state file to manage the transient environment for performance tuning
													f'terraform init -reconfigure -backend-config="bucket={terraform_state_s3_bucket.bucket_name}" -backend-config="key=pr-$BUILD_UUID.tfstate"',
													'terraform apply -auto-approve',
													# execute the state machine and get tuning results
													'sh execute-power-tuning.sh',
													'terraform destroy -auto-approve'
												]
											}
										}
									}),
									source=aws_codebuild.Source.code_commit(
										repository=lambda_repository),
									badge=True,
									environment=aws_codebuild.BuildEnvironment(
										build_image=aws_codebuild.LinuxBuildImage.AMAZON_LINUX_2_ARM_3,
										environment_variables={
											'REPOSITORY_NAME': aws_codebuild.BuildEnvironmentVariable(
												value=lambda_repository.repository_name),
											'STATE_MACHINE_ARN': aws_codebuild.BuildEnvironmentVariable(
												value=power_tuning_tools_application.get_att('Outputs.StateMachineARN').to_string())
										},
										compute_type=aws_codebuild.ComputeType.SMALL,
										privileged=True
									),
									role=terraform_apply_codebuild_iam_role)

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
																			 '$.detail.sourceReference'),
																		 'environmentVariablesOverride': [
																			 {
																				 'name': 'PULL_REQUEST_ID',
																				 'value': aws_events.EventField.from_path(
																					 '$.detail.pullRequestId')
																			 },
																			 {
																				 'name': 'SOURCE_COMMIT',
																				 'value': aws_events.EventField.from_path(
																					 '$.detail.sourceCommit')
																			 },
																			 {
																				 'name': 'DESTINATION_COMMIT',
																				 'value': aws_events.EventField.from_path(
																					 '$.detail.destinationCommit')
																			 }
																		 ]
																	 })
															 ))

		# Terraform CodeBuild projects
		terraform_plan_codebuild_project \
			= aws_codebuild.Project(self, 'TerraformPlanCodeBuildProject',
									build_spec=aws_codebuild.BuildSpec.from_object({
										'version': '0.2',
										'artifacts': {
											'files': ['*.tf', 'lambda/*', '*.zip', 'tfplan.out']
										},
										'phases': {
											'install': {
												'commands': [
													'yum -y install unzip',
													f'wget https://releases.hashicorp.com/terraform/{terraform_version}/terraform_{terraform_version}_linux_arm64.zip',
													f'unzip terraform_{terraform_version}_linux_arm64.zip',
													'mv terraform /usr/local/bin/'
												]
											},
											'build': {
												'commands': [
													f'terraform init -backend-config="bucket={terraform_state_s3_bucket.bucket_name}"',
													'terraform plan -out tfplan.out'
												]
											}
										}
									}),
									source=aws_codebuild.Source.code_commit(
										repository=lambda_repository),
									environment=aws_codebuild.BuildEnvironment(
										build_image=aws_codebuild.LinuxBuildImage.AMAZON_LINUX_2_ARM_3,
										compute_type=aws_codebuild.ComputeType.SMALL,
										privileged=True
									),
									role=terraform_plan_codebuild_iam_role)
		terraform_apply_codebuild_project \
			= aws_codebuild.Project(self, 'TerraformApplyCodeBuildProject',
									build_spec=aws_codebuild.BuildSpec.from_object({
										'version': '0.2',
										'phases': {
											'install': {
												'commands': [
													'yum -y install unzip',
													f'wget https://releases.hashicorp.com/terraform/{terraform_version}/terraform_{terraform_version}_linux_arm64.zip',
													f'unzip terraform_{terraform_version}_linux_arm64.zip',
													'mv terraform /usr/local/bin/'
												]
											},
											'build': {
												'commands': [
													f'terraform init -backend-config="bucket={terraform_state_s3_bucket.bucket_name}"',
													'terraform apply tfplan.out'
												]
											}
										}
									}),
									source=aws_codebuild.Source.code_commit(
										repository=lambda_repository),
									environment=aws_codebuild.BuildEnvironment(
										build_image=aws_codebuild.LinuxBuildImage.AMAZON_LINUX_2_ARM_3,
										compute_type=aws_codebuild.ComputeType.SMALL,
										privileged=True
									),
									role=terraform_apply_codebuild_iam_role)
		terraform_destroy_codebuild_project \
			= aws_codebuild.Project(self, 'TerraformDestroyCodeBuildProject',
									build_spec=aws_codebuild.BuildSpec.from_object({
										'version': '0.2',
										'phases': {
											'install': {
												'commands': [
													'yum -y install unzip',
													f'wget https://releases.hashicorp.com/terraform/{terraform_version}/terraform_{terraform_version}_linux_arm64.zip',
													f'unzip terraform_{terraform_version}_linux_arm64.zip',
													'mv terraform /usr/local/bin/'
												]
											},
											'build': {
												'commands': [
													f'terraform init -backend-config="bucket={terraform_state_s3_bucket.bucket_name}"',
													'terraform destroy -auto-approve'
												]
											}
										}
									}),
									source=aws_codebuild.Source.code_commit(
										repository=lambda_repository),
									environment=aws_codebuild.BuildEnvironment(
										build_image=aws_codebuild.LinuxBuildImage.AMAZON_LINUX_2_ARM_3,
										compute_type=aws_codebuild.ComputeType.SMALL,
										privileged=True
									),
									role=terraform_apply_codebuild_iam_role)

		# CI/CD pipeline resources
		# the UUID ensures that the bucket name will be unique for this demo, but do not use in production
		# when the CDK application is deployed again, a new UUID will be generated and thus a new bucket
		codepipeline_artifact_bucket_name = f'codepipeline-artifact-{uuid.uuid4()}'
		codepipeline_artifact_bucket \
			= aws_s3.Bucket(self, 'CodePipelineArtifactBucket',
							auto_delete_objects=True,
							block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
							bucket_name=codepipeline_artifact_bucket_name,
							removal_policy=RemovalPolicy.DESTROY)
		cicd_pipeline \
			= aws_codepipeline.Pipeline(self, 'LambdaCICDPipeline',
										artifact_bucket=codepipeline_artifact_bucket,
										pipeline_name='LambdaCICDPipeline')
		# source
		source_artifact = aws_codepipeline.Artifact()
		source_stage = cicd_pipeline.add_stage(stage_name='Source')
		source_stage.add_action(
			aws_codepipeline_actions.CodeCommitSourceAction(action_name='CodeCommitSource',
															branch=main_branch_name,
															output=source_artifact,
															repository=lambda_repository))
		# approve build
		approve_build_stage = cicd_pipeline.add_stage(stage_name='ApproveBuild')
		build_manual_approval_action = aws_codepipeline_actions.ManualApprovalAction(action_name='BuildManualApproval')
		approve_build_stage.add_action(build_manual_approval_action)
		# build
		build_stage = cicd_pipeline.add_stage(stage_name='Build')
		terraform_plan_artifact = aws_codepipeline.Artifact()
		build_stage.add_action(aws_codepipeline_actions.CodeBuildAction(action_name='TerraformPlan',
																		input=source_artifact,
																		outputs=[terraform_plan_artifact],
																		project=terraform_plan_codebuild_project))
		# approve deploy
		approve_deploy_stage = cicd_pipeline.add_stage(stage_name='ApproveDeploy')
		deploy_manual_approval_action = aws_codepipeline_actions.ManualApprovalAction(
			action_name='DeployManualApproval')
		approve_deploy_stage.add_action(deploy_manual_approval_action)
		# deploy
		deploy_stage = cicd_pipeline.add_stage(stage_name='Deploy')
		deploy_stage.add_action(aws_codepipeline_actions.CodeBuildAction(action_name='TerraformApply',
																		 input=terraform_plan_artifact,
																		 project=terraform_apply_codebuild_project))
