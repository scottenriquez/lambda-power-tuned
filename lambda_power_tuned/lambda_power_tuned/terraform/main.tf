terraform {
  backend "s3" {
    key    = "infrastructure.tfstate"
    region = "us-west-2"
  }
}

provider "aws" {
  region = "us-west-2"
}
