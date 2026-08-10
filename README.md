# RPA Guidance PoC - Local Development

Local development support for running / developing RPA guidance use case PoC locally using Docker Compose.

## Prerequisites

- Docker
- Docker Compose
- Amazon Bedrock with the ability to create inference profiles and guardrails (for LLM access)
- uv - [Installation Guide](https://docs.astral.sh/uv/getting-started/installation/#installing-uv)
- Python 3.13 or higher - We recommend using uv to manage your Python environment.
- Git

## Repositories

| Service | Type | Language |
|---------|------|----------|
| [ai-uc-rpa-guidance-ui](https://github.com/DEFRA/ai-uc-rpa-guidance-fe) | Frontend | JavaScript |
| [ai-uc-rpa-guidance-runtime](https://github.com/DEFRA/ai-uc-rpa-guidance) | Backend/Runtime | Python |
| [ai-uc-rpa-guidance-evals-runtime](https://github.com/DEFRA/ai-uc-rpa-guidance-evals-runtime) | Evaluations runtime | Python |

## Local Development

You will need to clone this repository and sync the environment before running the scripts.

By default, service repositories are cloned into the parent directory of `ai-uc-rpa-guidance`. Therefore, we recommend creating a directory specifically for the RPA Guidance project and cloning all repositories into it.

```bash
git clone https://github.com/DEFRA/ai-uc-rpa-guidance-dev

cd ai-uc-rpa-guidance-dev/

uv sync --frozen
```

### Cloning Repositories

This project contains a script to clone all the required repositories. This works by checking the service-compose directory for the services and cloning them if they do not exist.

To clone the repositories, run the following command:

```bash
uv run task clone
```

Your cloned repositories will be located in the `ai-uc-rpa-guidance` directory created in the previous step.

### Environment Configuration
This repository uses a `.env` file for environment variable configuration. This must be created for the Docker Compose project to start.

> [!IMPORTANT]
> The `.env` file should not be committed to version control. Add it to your `.gitignore` file to keep sensitive configuration data secure.

There is an example environment file located at `.env.example`. You can create your own `.env` file by copying the example file:
```bash
cp .env.example .env
```

Refer to the table below for environment variables, their defaults, and whether they're required by the services.

| Variable | Default | Required | Description |
|---|---|:---:|---|
| AWS_REGION | eu-west-2 | No | Primary AWS region used by services (runtime default: `eu-west-2`) |
| AWS_DEFAULT_REGION | eu-west-2 | No | Fallback AWS region environment variable |
| AWS_ACCESS_KEY_ID | test | No | AWS access key (use local/test credentials for local dev) |
| AWS_SECRET_ACCESS_KEY | test | No | AWS secret key (use local/test credentials for local dev) |
| AWS_EMF_ENVIRONMENT | local | No | Environment label for EMF (embedded metrics) |
| AWS_EMF_AGENT_ENDPOINT | tcp://127.0.0.1:25888 | No | EMF agent endpoint for metrics ingestion |
| AWS_EMF_LOG_GROUP_NAME | log-group-name | No | CloudWatch EMF log group name (local placeholder) |
| AWS_EMF_LOG_STREAM_NAME | log-stream-name | No | CloudWatch EMF log stream name (local placeholder) |
| AWS_EMF_NAMESPACE | namespace | No | EMF metrics namespace |
| AWS_EMF_SERVICE_NAME | service-name | No | Logical service name for EMF metrics |
| AWS_EMF_SERVICE_TYPE | python-backend-service | No | Service type used by EMF instrumentation |
| ASSETS_S3_BUCKET | ai-uc-rpa-guidance-evals-assets | No | S3 bucket used by the evals runtime for assets |
| CA_BUNDLE_DIR | _(empty)_ | No | Directory of `*.crt` certificates to add to the containers' trust store. Only needed behind a TLS-inspecting proxy — see [Corporate proxy / custom CAs](#corporate-proxy--custom-cas) |

### Starting the Services

A single docker-compose project has been created that orchestrates all microservices, dependencies, and performs any necessary setup tasks such as database migrations.

All configuration is stored in the `.env` file. Before starting the services, ensure that the `.env` file is correctly configured. The services will use default values if no `.env` file is present.

To start all services, run the following command:

```bash
docker compose up --build
```

To stop the services, run the following command:

```bash
docker compose down
```

The services can still be started individually directly from their respective repositories. However, this project is intended to streamline local development by having a common entry point for all services.

### Corporate proxy / custom CAs

On a network that intercepts TLS (for example AVD), containers will not trust the
proxy's certificate and calls to PyPI, Bedrock and S3 fail with
`CERTIFICATE_VERIFY_FAILED`. Set `CA_BUNDLE_DIR` in your `.env` to a directory
containing the certificates to trust:

```bash
CA_BUNDLE_DIR=/path/to/certs
```

Then populate that directory with the [`certs`](#certs) script, which works out
which certificates are needed and writes them there:

```bash
uv run task certs
```

Every `*.crt` file in that directory is appended to the containers' system trust
store at build time (duplicates are removed), which covers `uv` during the build
and `httpx`, `boto3` and `pymongo` at runtime. Only `*.crt` files are read — so
a stray private key can never end up in an image — and they must be PEM-encoded
(`-----BEGIN CERTIFICATE-----`); rename a PEM-encoded `.pem` file to `.crt` to
include it.

> [!IMPORTANT]
> Include the **whole chain** up to and including the self-signed root, not just
> the issuing CA. A partial chain fails with `unable to get issuer certificate`
> rather than a more obvious trust error.

Leave `CA_BUNDLE_DIR` unset if you are not behind such a proxy — the default is an
empty directory and the build is unaffected.

`docker compose up --build` picks up certificate changes automatically: the trust
store layer is keyed on the *contents* of `CA_BUNDLE_DIR`, so it rebuilds when the
certificates change and is reused when they have not. No `--no-cache` needed.

## Network

All services run on a shared Docker network named `ai-uc-rpa-guidance` to enable inter-service communication.

## Script Documentation

This project contains a number of scripts to streamline local microservice development.

### Clone

Clones the repositories for each microservice into the parent directory.

```bash
uv run task clone
```

### Pull

Pulls the latest remote changes for each microservice.

```bash
uv run task pull
```

### Update

Switches to and pulls the latest main branch for each microservice.

```bash
uv run task update
```

### Certs

Extracts the certificates needed behind a TLS-inspecting proxy into `CA_BUNDLE_DIR`.
Only needed on such a network — see [Corporate proxy / custom CAs](#corporate-proxy--custom-cas).

```bash
uv run task certs
```

It connects to the services' upstream hosts, takes the chain each one actually
serves, then walks upwards through your machine's trust stores (including the
Windows certificate store under WSL) until it reaches a self-signed root — the
part the proxy does not send and the usual cause of `unable to get issuer
certificate`. Chains that are already publicly trusted are skipped. Re-run it if
the corporate certificates are rotated.
