data "aws_iam_policy_document" "assume_role" {
	statement {
		effect = "Allow"

		principals {
			type        = "Service"
			identifiers = ["lambda.amazonaws.com"]
		}

		actions = ["sts:AssumeRole"]
	}
}

resource "random_id" "iam_role_name" {
    byte_length = 8
}

resource "aws_iam_role" "iam_for_lambda" {
	name               = "iam_for_lambda-${random_id.iam_role_name.id}"
	assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

data "archive_file" "lambda" {
	type        = "zip"
	source_file = "lambda_function.py"
	output_path = "lambda_function_payload.zip"
}

resource "random_id" "lambda" {
    byte_length = 8
}

resource "aws_lambda_function" "test_lambda" {
	architectures = ["arm64"]
	filename      = "lambda_function_payload.zip"
	function_name = "target_function-${random_id.lambda.id}"
	role          = aws_iam_role.iam_for_lambda.arn
	handler       = "lambda_function.lambda_handler"
	memory_size   = 128

	source_code_hash = data.archive_file.lambda.output_base64sha256

	runtime = "python3.11"
}

output "arn" {
  value = aws_lambda_function.test_lambda.arn
}
