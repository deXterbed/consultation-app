# MediNotes Pro

AI-powered medical consultation assistant. A FastAPI backend serves a Next.js static frontend, packaged as a single container for AWS Lambda via the [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter).

## Architecture

```
Browser ──► Lambda URL ──► Lambda Web Adapter ──► FastAPI ──► Next.js static files
                              (translates HTTP         │
                               events to FastAPI)      └──► OpenAI API
```

- **Frontend**: Next.js static export (pages router) with Clerk authentication
- **Backend**: FastAPI with SSE streaming for AI consultation summaries
- **Deployment**: Single Docker image → ECR → Lambda (with response streaming)

## Prerequisites

- Docker
- AWS CLI (`aws configure` with credentials)
- An [OpenAI API key](https://platform.openai.com/api-keys)
- A [Clerk](https://clerk.com) application (for authentication)

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Build | Clerk publishable key (starts with `pk_`) — baked into the frontend at build time |
| `CLERK_JWKS_URL` | Runtime | Clerk JWKS endpoint for verifying auth tokens |
| `OPENAI_API_KEY` | Runtime | OpenAI API key for generating summaries |

These are stored in `.env.local` (see `.env.local.example`).

## Local Development

```bash
# Install frontend dependencies
npm install

# Run Next.js dev server (http://localhost:3000)
npm run dev
```

The FastAPI backend is only needed in production. During development, Next.js handles both frontend and API routes via its dev server.

## Building the Docker Image

```bash
# Build for local testing (ARM, matches your Mac)
export $(cat .env | grep -v '^#' | xargs)

docker build \
  --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY="$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY" \
  -t consultation-app .

# Build for Lambda (x86_64 — Lambda's native architecture)
docker build \
  --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY="$NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY" \
  -t consultation-app .
```

> **Note:** The `--build-arg` reads from your shell environment. If the variable isn't exported, use the value directly:
> ```bash
> --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY="pk_test_..."
> ```

## Running Locally

```bash
docker run -p 8000:8000 \
  -e CLERK_SECRET_KEY="$CLERK_SECRET_KEY" \
  -e CLERK_JWKS_URL="$CLERK_JWKS_URL" \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  consultation-app
```

Open http://localhost:8000.

## Deploying to AWS Lambda

### 1. Create an ECR Repository

```bash
aws ecr create-repository --repository-name consultation-app --region us-east-1
```

### 2. Authenticate Docker with ECR

```bash
aws ecr get-login-password --region $DEFAULT_AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$DEFAULT_AWS_REGION.amazonaws.com
```

### 3. Tag and Push the Image

```bash
docker tag consultation-app:latest "$env:AWS_ACCOUNT_ID.dkr.ecr.$env:DEFAULT_AWS_REGION.amazonaws.com/consultation-app:latest"

docker push "$env:AWS_ACCOUNT_ID.dkr.ecr.$env:DEFAULT_AWS_REGION.amazonaws.com/consultation-app:latest"
```

### 4. Create the Lambda Function

```bash
aws lambda create-function \
  --function-name consultation-app \
  --package-type Image \
  --code ImageUri=$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/consultation-app:latest \
  --role arn:aws:iam::$ACCOUNT_ID:role/lambda-execution-role \
  --timeout 30 \
  --memory-size 256 \
  --region us-east-1
```

> **IAM Role:** You need a Lambda execution role with `lambda.amazonaws.com` trust policy and `AWSLambdaBasicExecutionRole` managed policy. Create one if it doesn't exist:
> ```bash
> aws iam create-role --role-name lambda-execution-role \
>   --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
> aws iam attach-role-policy --role-name lambda-execution-role \
>   --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
> ```

### 5. Set Environment Variables

```bash
aws lambda update-function-configuration \
  --function-name consultation-app \
  --environment "Variables={
    CLERK_JWKS_URL=https://your-clerk-app.clerk.accounts.dev/.well-known/jwks.json,
    OPENAI_API_KEY=sk-...
  }" \
  --region us-east-1
```

### 6. Create a Function URL

```bash
aws lambda create-function-url-config \
  --function-name consultation-app \
  --auth-type NONE \
  --region us-east-1
```

This returns a URL like `https://xxxxxxxxx.lambda-url.us-east-1.on.aws/`. Open it in your browser.

> **Auth:** The function URL uses `--auth-type NONE` because authentication is handled by Clerk at the application level, not by AWS. For production, consider adding AWS WAF or a CloudFront distribution in front of the URL.

### 7. Enable Response Streaming

Lambda response streaming is required for the SSE (Server-Sent Events) endpoint to work:

```bash
aws lambda update-function-configuration \
  --function-name consultation-app \
  --response-streaming-options ResponseStreaming=ALL \
  --region us-east-1
```

### Updating the Function

After rebuilding the image:

```bash
docker tag consultation-app:latest "$env:AWS_ACCOUNT_ID.dkr.ecr.$env:DEFAULT_AWS_REGION.amazonaws.com/consultation-app:latest"
docker push "$env:AWS_ACCOUNT_ID.dkr.ecr.$env:DEFAULT_AWS_REGION.amazonaws.com/consultation-app:latest"

aws lambda update-function-code \
  --function-name consultation-app \
  --image-uri $AWS_ACCOUNT_ID.dkr.ecr.$DEFAULT_AWS_REGION.amazonaws.com/consultation-app:latest \
  --region $DEFAULT_AWS_REGION
```

## How the Lambda Web Adapter Works

The Dockerfile includes a Lambda extension that bridges the Lambda runtime to your FastAPI app:

1. Lambda invokes the container with an HTTP event
2. The Lambda Web Adapter (in `/opt/extensions/`) receives it
3. It forwards the event as a normal HTTP request to FastAPI on `localhost:8000`
4. FastAPI processes it (serves static files or calls OpenAI)
5. The adapter converts the HTTP response back to a Lambda response

This lets the same container run locally with `docker run` and on Lambda without code changes.

## Project Structure

```
saas-aws/
├── api/
│   ├── server.py          # FastAPI app (routes, static serving)
│   └── requirements.txt   # Python dependencies
├── pages/                 # Next.js pages
│   ├── index.tsx          # Landing page with Clerk auth
│   ├── product.tsx        # Consultation form
│   ├── sign-in/           # Clerk sign-in
│   ├── sign-up/           # Clerk sign-up
│   └── _app.tsx           # Clerk provider wrapper
├── styles/
│   └── globals.css        # Tailwind CSS
├── public/                # Static assets
├── Dockerfile             # Multi-stage build (Next.js → Python)
├── next.config.ts         # Next.js config (static export)
└── .env.local             # Environment variables (not committed)
```
