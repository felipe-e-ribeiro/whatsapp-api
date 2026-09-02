import os

import pytest


@pytest.fixture(autouse=True)
def aws_default_region(monkeypatch):
    """Every v2 lambda module (src/links_*.py) creates its boto3 client or
    resource at import time, with no explicit region_name — that's fine in
    Lambda, where the runtime always sets AWS_REGION for us.

    moto's mock_aws() intercepts the API calls those clients make, but it
    does not supply a region: that still comes from the normal boto3/
    botocore resolution chain (env var, ~/.aws/config, ...). CI provides one
    via the AWS_REGION secret (see .github/workflows/ci.yml); locally,
    whatever AWS config/env you already have is reused. Without either, a
    module import raises botocore.exceptions.NoRegionError.

    moto intercepts every AWS call itself, so the actual value never
    matters for these tests to pass — only that *some* region is present so
    boto3 can resolve an endpoint. The placeholder below is deliberately not
    a real AWS region: this is a public repo and there's no reason for it to
    say which region actually runs the deployed stack.
    """
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "test-region-1"
    monkeypatch.setenv("AWS_DEFAULT_REGION", region)
