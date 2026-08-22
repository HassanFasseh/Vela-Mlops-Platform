# Vela

Open-source MLOps for regulated industries. Deploy any model, detect drift, understand why — on your infrastructure, under your control.

![Dashboard](docs/screenshots/dashboard.png)

## The problem

A data scientist deploys a model on Friday. By Monday something has changed — the data, the behavior, the confidence. The model is silently wrong and nobody knows why. Most teams find out when a business metric drops, weeks later.

Vela fixes this. It watches your models continuously, tells you when something changes, and explains what happened in plain language — automatically, on your own servers. No data leaves your network.

Built for organizations that cannot use HuggingFace Spaces or cloud ML services: hospitals, banks, universities, government agencies.

## What it does

**Deploy** — Submit a HuggingFace model name or upload your own weights. GitHub Actions builds a multi-arch Docker image and deploys it to Kubernetes. Live in 5 to 10 minutes.

**Monitor** — Prometheus scrapes metrics every 15 seconds. Evidently AI computes statistical drift across a sliding window and tracks which specific signals shifted: confidence score, label distribution, input length. Redis persists state across restarts.

**Explain** — When drift is detected, an LLM generates a plain-language summary naming the drifted columns and their p-values. Not just "drift detected" — "your confidence score and label distribution have both shifted significantly since the deploy 2 hours ago, while latency remains stable."

**Act** — When drift crosses a configured threshold, Vela automatically opens a GitHub issue, fires a webhook, or triggers a retraining pipeline. No human needs to notice and react.

**Control** — Multi-tenant workspaces with JWT auth. Teams with role-based model permissions. Access request and approval flow. API keys scoped to specific teams and models.

![Workspace](docs/screenshots/workspace.png)

## Live demo

| Service | URL |
|---|---|
| Dashboard | http://51.170.140.102/dashboard |
| Auth / Workspaces | http://51.170.140.102/auth/login-page |
| Grafana | http://51.170.129.103 |

## How it works

**Deployment loop** — runs once per model

```
Dashboard form  →  GitHub Actions  →  Docker build (arm64)  →  Registry push  →  kubectl deploy  →  Live endpoint
```

**Operations loop** — runs continuously

```
Prometheus scrape  →  Evidently drift detection  →  Event correlation  →  LLM explanation  →  Dashboard (30s refresh)
```

![Timeline](docs/screenshots/timeline.png)

## Quick start

### Run locally

```bash
git clone https://github.com/HassanFasseh/vela
cd vela
cp .env.example .env
# Fill in GROQ_API_KEY and GEMINI_API_KEY
docker compose up
```

Open `http://localhost:8000/dashboard`

### Deploy to production (Kubernetes on Oracle Cloud Always Free)

Requirements: Oracle Cloud account, Terraform, kubectl, Docker with buildx.

```bash
cd terraform
terraform init
terraform apply
```

Configure your GitHub Actions secrets and push. CI/CD handles the rest.

## API reference

### Authenticated prediction

```bash
curl -X POST http://your-vela/api/v1/predict \
  -H "X-API-Key: aodp_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"text": "patient discharge notes", "model_id": 1}'
```

```json
{
  "workspace_id": 2,
  "model_id": 1,
  "result": {
    "label": "POSITIVE",
    "score": 0.9999
  }
}
```

### Upload your own model weights

```bash
curl -X POST http://your-vela/api/v1/upload-model \
  -H "X-API-Key: aodp_your_key_here" \
  -F "file=@clinical_model_v2.bin" \
  -F "model_name=clinical-sentiment-v2" \
  -F "workspace_id=1"
```

### Configure automated remediation

```bash
curl -X POST http://your-vela/api/v1/remediations \
  -H "X-API-Key: aodp_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_id": 1,
    "drift_threshold": 0.5,
    "action_type": "github_issue",
    "target": "your-org/your-repo"
  }'
```

When triggered, Vela creates a GitHub issue like this:

![GitHub Issue](docs/screenshots/github-issue.png)

### Request workspace access

```bash
curl -X POST http://your-vela/access-requests \
  -H "Authorization: Bearer your_jwt_token" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": 1,
    "team_id": 1,
    "deployment_id": 2,
    "message": "Need access to the clinical NLP model for the Q3 study"
  }'
```

## Access control

```
Workspace
  ├── Models (deployed and documented by admins)
  ├── Teams
  │     ├── Radiology Team   →  Model A only
  │     └── Research Team    →  All models
  └── API Keys (scoped per team and per model)
```

Users request access to a workspace or team. Admins approve or deny. Approved users are automatically added and get API keys scoped to their team's permitted models. Every prediction is attributed to a workspace.

![Workspaces](docs/screenshots/workspaces.png)

## Model cards

Every deployed model can have a documented model card covering:

- What the model does
- Dataset used for training (name, source, size)
- License
- Performance notes and benchmark results
- Known limitations and failure modes

Model cards are queryable via API and visible in the workspace dashboard.

## Stack

| Layer | Technology |
|---|---|
| Orchestration | Kubernetes (OKE, ARM64) |
| Infrastructure | Terraform, Oracle Cloud Always Free |
| CI/CD | GitHub Actions, multi-arch buildx |
| Model serving | FastAPI, HuggingFace Transformers |
| Monitoring | Prometheus, Grafana, kube-prometheus-stack |
| Drift detection | Evidently AI 0.7.21, Redis |
| LLM explanation | Groq (openai/gpt-oss-20b), Gemini Flash fallback |
| Auth | JWT (python-jose), bcrypt |
| Database | PostgreSQL, Alembic migrations |
| Object storage | MinIO (S3-compatible) |
| Local dev | Docker Compose |

## Environment variables

Copy `.env.example` to `.env`:

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key for LLM summaries |
| `GEMINI_API_KEY` | Yes | Google AI Studio key (Gemini Flash fallback) |
| `GITHUB_TOKEN` | Yes | Fine-grained PAT with Actions and Issues write |
| `GITHUB_REPO` | Yes | Your repo in owner/repo format |
| `MODEL_SERVICE_URL` | No | Overrides model service URL (local dev) |
| `PROMETHEUS_URL` | No | Overrides Prometheus URL (local dev) |

## Honest limitations

- **Single-node cluster** on Oracle Always Free. Not suitable for high-availability production. Swap to a multi-node cluster for real workloads.
- **Public dashboard** — `/dashboard` requires no login currently. Auth-gated dashboard is on the roadmap.
- **3 LoadBalancer limit** — Oracle Free tier caps at 3. User-deployed models use ClusterIP and are accessible in-cluster only. An ingress controller removes this constraint.
- **Batch drift detection** — drift is computed every 30 predictions, not as a continuous stream.

## Roadmap

- [ ] Dashboard authentication (require workspace login to view)
- [ ] Frontend for teams and permissions management
- [ ] A/B traffic splitting between model versions
- [ ] Helm chart for one-command deployment
- [ ] Email and Slack drift alerts
- [ ] Federated drift signal sharing across organizations (privacy-preserving)
- [ ] GPU node support

## Contributing

Open an issue before submitting a large PR.

```bash
# Run locally
docker compose up

# Generate a migration after changing models
alembic --config backend/alembic.ini revision --autogenerate -m "description"

# Run tests
pytest backend/tests/
```

## License

Apache 2.0

## Author

Hassan Fasseh, Data Science and AI Engineering, Morocco
[GitHub](https://github.com/HassanFasseh)