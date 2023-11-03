#!/bin/bash

# obtain ARN from Terraform and build input file
TARGET_LAMBDA_ARN=$(terraform output -raw arn)
echo $(jq --arg arn $TARGET_LAMBDA_ARN '. += {"lambdaARN" : $arn}' power-tuning-input.json) > power-tuning-input-$BUILD_UUID.json
POWER_TUNING_INPUT_JSON=$(cat power-tuning-input-$BUILD_UUID.json)

# start execution
EXECUTION_ARN=$(aws stepfunctions start-execution --state-machine-arn $STATE_MACHINE_ARN --input "$POWER_TUNING_INPUT_JSON"  --query 'executionArn' --output text)

echo -n "Execution started..."

# poll execution status until completed
while true;
do
    # retrieve execution status
    STATUS=$(aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN --query 'status' --output text)

    if test "$STATUS" == "RUNNING"; then
        # keep looping and wait if still running
        echo -n "."
        sleep 1
    elif test "$STATUS" == "FAILED"; then
        # exit if failed
        echo -e "\nThe execution failed, you can check the execution logs with the following script:\naws stepfunctions get-execution-history --execution-arn $EXECUTION_ARN"
        break
    else
        # print execution output if succeeded
        echo $STATUS
        echo "Execution output: "
        # retrieve output
        aws stepfunctions describe-execution --execution-arn $EXECUTION_ARN --query 'output' --output text > power-tuning-output-$BUILD_UUID.json

        break
    fi
done

# get output URL and comment on pull request
POWER_TUNING_OUTPUT_URL=$(cat power-tuning-output-$BUILD_UUID.json | jq -r '.stateMachine .visualization')
aws codecommit post-comment-for-pull-request --repository-name $REPOSITORY_NAME --pull-request-id $PULL_REQUEST_ID --content "Lambda tuning is complete. See the [results for full details]($POWER_TUNING_OUTPUT_URL)." --before-commit-id $SOURCE_COMMIT --after-commit-id $DESTINATION_COMMIT
