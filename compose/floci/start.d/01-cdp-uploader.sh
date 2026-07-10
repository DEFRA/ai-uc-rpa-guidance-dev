#!/bin/bash

export AWS_REGION=eu-west-2
export AWS_DEFAULT_REGION=eu-west-2
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test

echo "[INIT SCRIPT] Creating buckets" >&2

aws s3 mb --endpoint-url=http://localhost:4566 s3://cdp-uploader-quarantine || true
aws s3 mb --endpoint-url=http://localhost:4566 s3://my-bucket || true

echo "[INIT SCRIPT] Creating queues" >&2

# queues
aws sqs create-queue --endpoint-url=http://localhost:4566 --queue-name cdp-clamav-results || true
aws sqs create-queue --endpoint-url=http://localhost:4566 --queue-name cdp-uploader-scan-results-callback.fifo --attributes "{\"FifoQueue\":\"true\",\"ContentBasedDeduplication\": \"true\"}" || true

# test harness
aws sqs create-queue --endpoint-url=http://localhost:4566 --queue-name mock-clamav || true
aws s3api put-bucket-notification-configuration --endpoint-url=http://localhost:4566 --bucket cdp-uploader-quarantine --notification-configuration '{"QueueConfigurations": [{"QueueArn": "arn:aws:sqs:eu-west-2:000000000000:mock-clamav","Events": ["s3:ObjectCreated:*"]}]}' || true
aws sqs create-queue --endpoint-url=http://localhost:4566 --queue-name cdp-uploader-download-requests || true
