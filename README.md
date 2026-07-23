# infra-provisioner

A self-service infrastructure provisioning tool. Submit a request through a web dashboard, and it automatically creates or deletes AWS resources on your behalf — starting with S3 buckets — while logging every request and its outcome.

Built as a learning project to understand how the pieces of a real internal platform tool fit together: a request store, a backend that acts on requests, a frontend to submit and track them, and a CI/CD pipeline to deploy changes safely.

## How it works

**Dashboard → Lambda Function URL → DynamoDB + S3**

1. **Dashboard** (`frontend/index.html`) — a static HTML page where you submit a create/delete request and view request history. Calls the Lambda Function URL directly with a shared API key for basic access control.
2. **Lambda function** (`lambda/lambda_function.py`) — receives the request, validates it, performs the action (currently: create/delete an S3 bucket), and logs the outcome.
3. **DynamoDB table** (`infra-requests`) — stores every request: what was asked for, when, and whether it succeeded or failed.
4. **CI/CD** (`.github/workflows/deploy.yml`) — automatically deploys changes to `lambda/lambda_function.py` to the live Lambda function on every push to `main`.

## Supported resource types

- `s3_bucket` — create or delete an S3 bucket (must be empty to delete)

## Safety features

- **Least-privilege IAM** — the Lambda's execution role can only create/delete S3 buckets and read/write the `infra-requests` table, nothing else in the account.
- **Input validation** — bucket names are checked against S3's naming rules before any AWS call is made.
- **Delete confirmation** — the dashboard requires an explicit confirmation before submitting a delete request.
- **Friendly error messages** — common AWS errors (bucket not empty, name already taken, bucket doesn't exist) are translated into plain-language messages instead of raw exceptions.
- **API key check** — the Lambda rejects any request that doesn't include the correct shared secret, so the publicly-reachable Function URL can't be used by strangers who stumble across it.

## Project structure

infra-provisioner/
├── lambda/
│ └── lambda_function.py # Backend logic
├── frontend/
│ └── index.html # Dashboard UI
├── .github/
│ └── workflows/
│ └── deploy.yml # CI/CD pipeline
└── README.md

## Possible future work

- Support additional resource types (e.g. EC2 instances)
- Move the API key to a more robust auth mechanism (e.g. API Gateway + Cognito)
- Add a "confirm before create" step, similar to delete
- Add automated tests for the Lambda function
