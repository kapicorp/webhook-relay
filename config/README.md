# Testing Webhook Relay with curl

This guide shows how to test your webhook relay system using `curl` to simulate webhook payloads from different sources.

## Prerequisites

- The webhook relay collector is running at `http://localhost:8000` (adjust the URL as needed)
- You have `curl` installed
- You have `python` installed (for generating signatures)

## 1. Testing with GitHub Webhook Payload

GitHub webhooks include a signature in the `X-Hub-Signature-256` header for verification. We'll need to generate this signature.

### Step 1: Save the GitHub payload to a file

Create a file named `github-payload.json` with this content:

```json
{
  "ref": "refs/heads/main",
  "repository": {
    "id": 123456,
    "name": "test-repo",
    "full_name": "octocat/test-repo",
    "html_url": "https://github.com/octocat/test-repo"
  },
  "pusher": {
    "name": "octocat",
    "email": "octocat@github.com"
  },
  "commits": [
    {
      "id": "abc123def456",
      "message": "Test commit",
      "timestamp": "2023-01-01T12:00:00Z",
      "author": {
        "name": "Octocat",
        "email": "octocat@github.com"
      },
      "url": "https://github.com/octocat/test-repo/commit/abc123def456"
    }
  ]
}
```

### Step 2: Generate the signature

Replace `YOUR_WEBHOOK_SECRET` with the actual GitHub webhook secret you configured:

```bash
# For macOS/Linux
GITHUB_SIGNATURE=$(echo -n "$(cat github-payload.json)" | openssl dgst -sha256 -hmac "YOUR_WEBHOOK_SECRET" | sed 's/^.* /sha256=/')

# For Windows PowerShell
$PAYLOAD = Get-Content -Raw -Path github-payload.json
$HMACSHA = New-Object System.Security.Cryptography.HMACSHA256
$HMACSHA.key = [Text.Encoding]::ASCII.GetBytes("YOUR_WEBHOOK_SECRET")
$SIGNATURE = "sha256=" + [Convert]::ToBase64String($HMACSHA.ComputeHash([Text.Encoding]::ASCII.GetBytes($PAYLOAD)))
```

Alternatively, use this Python script to generate the signature:

```python
import hmac
import hashlib
import sys

# Replace with your actual webhook secret
webhook_secret = "YOUR_WEBHOOK_SECRET"

# Read payload from file
with open("github-payload.json", "rb") as f:
    payload = f.read()

# Calculate signature
signature = hmac.new(
    webhook_secret.encode(),
    payload,
    hashlib.sha256
).hexdigest()

print(f"sha256={signature}")
```

### Step 3: Send the webhook with curl

```bash
curl -X POST \
  http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "User-Agent: GitHub-Hookshot/abcdef" \
  -H "X-GitHub-Event: push" \
  -H "X-Hub-Signature-256: $GITHUB_SIGNATURE" \
  -d @github-payload.json
```

## 2. Testing with GitLab Webhook Payload

### Step 1: Save the GitLab payload to a file

Create a file named `gitlab-payload.json` with this content:

```json
{
  "object_kind": "push",
  "event_name": "push",
  "project": {
    "id": 123456,
    "name": "test-project",
    "web_url": "https://gitlab.com/namespace/test-project"
  },
  "user_name": "Test User",
  "user_email": "test@example.com",
  "commits": [
    {
      "id": "abc123def456",
      "message": "Test commit",
      "timestamp": "2023-01-01T12:00:00Z",
      "author": {
        "name": "Test User",
        "email": "test@example.com"
      },
      "url": "https://gitlab.com/namespace/test-project/-/commit/abc123def456"
    }
  ],
  "total_commits_count": 1,
  "ref": "refs/heads/main"
}
```

### Step 2: Send the webhook with curl

For GitLab, replace `YOUR_GITLAB_TOKEN` with the secret token you configured:

```bash
curl -X POST \
  http://localhost:8000/webhooks/gitlab \
  -H "Content-Type: application/json" \
  -H "User-Agent: GitLab/15.0" \
  -H "X-Gitlab-Event: Push Hook" \
  -H "X-Gitlab-Token: YOUR_GITLAB_TOKEN" \
  -d @gitlab-payload.json
```

## 3. Testing with Custom Webhook (No Signature Verification)

For webhooks without signature verification, you can use this simplified approach:

### Step 1: Save the custom payload to a file

Create a file named `custom-payload.json` with this content:

```json
{
  "event_type": "custom_event",
  "timestamp": "2023-01-01T12:00:00Z",
  "data": {
    "id": 12345,
    "name": "Test Event",
    "description": "This is a test event for the webhook relay"
  },
  "metadata": {
    "source": "test-system",
    "version": "1.0"
  }
}
```

### Step 2: Send the webhook with curl

```bash
curl -X POST \
  http://localhost:8000/webhooks/custom \
  -H "Content-Type: application/json" \
  -H "User-Agent: TestAgent/1.0" \
  -d @custom-payload.json
```

## Verifying the Results

After sending the webhook, you should:

1. Check the Collector logs to ensure the webhook was received and queued
2. Check the Queue (GCP Pub/Sub or AWS SQS) to see if the message was published
3. Check the Forwarder logs to see if the message was received and forwarded
4. Check the target service logs to see if the webhook was delivered

You can also check the metrics endpoints for successful operations:
- Collector metrics: `http://localhost:9090/metrics`
- Forwarder metrics: `http://localhost:9091/metrics`

Look for metrics like:
- `webhook_relay_received_total`
- `webhook_relay_queue_publish_total`
- `webhook_relay_queue_receive_total` 
- `webhook_relay_forward_total`