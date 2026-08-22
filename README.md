# AI-Operated Model Deployment Platform

> Self-hosted, privacy-first MLOps platform. Deploy any HuggingFace model as a live API, monitor it continuously, detect drift, and get plain-language explanations — without sending a byte of data outside your infrastructure.

![Dashboard](docs/screenshots/dashboard.png)

## Why this exists

Most ML tools solve the training problem. This solves the operations problem — what happens after a model is deployed, when nobody is watching, and the world keeps changing.

Organizations with data privacy requirements — hospitals, banks, universities, government agencies — cannot send data to HuggingFace Spaces or cloud ML services. This platform runs entirely on your own infrastructure. Apache 2.0 licensed.

## What it does

**Deploy** — Submit a HuggingFace model name through the dashboard. GitHub Actions builds a multi-arch Docker image, pushes it to your registry, and deploys it to Kubernetes. Live in 5–10 minutes. Or upload your own trained model weights directly.

**Monitor** — Prometheus scrapes metrics every 15 seconds. Evidently AI computes drift across a sliding window, comparing the current input distribution against a reference baseline. Redis persists state across pod restarts.

**Explain** — When drift is detected, the platform identifies which specific signals shifted — confidence score, label distribution, input length — and generates a plain-language summary via Groq or Gemini Flash. Not just "drift detected" but "your confidence score and label distribution have both shifted significantly since the deploy 2 hours ago, while latency remains stable."

**Act** — When drift crosses a configured threshold, the platform automatically opens a GitHub issue, fires a webhook, or triggers a retraining pipeline. No human needs to notice and react.

**Control** — Multi-tenant workspaces with JWT auth. Teams with role-based model permissions. Access request and approval flow. API keys scoped to specific teams and models.

![Workspace](docs/screenshots/workspace.png)

## Live demo

| Service | URL |
|---|---|
| Dashboard | http://51.170.140.102/dashboard |
| Auth / Workspaces | http://51.170.140.102/auth/login-page |
| Grafana | http://51.170.129.103 |

## Architecture

**Deployment loop** *(runs once per model)*

```
Dashboard form  →  GitHub Actions  →  Docker build (arm64)  →  Push to OCIR  →  kubectl deploy  →  Live endpoint
```

**Operations loop** *(runs continuously)*

```
Prometheus scrape /metrics  →  Evidently drift detection  →  Event correlation
    →  Groq / Gemini LLM summary  →  Dashboard auto-refresh (30s)
```

![Timeline](docs/screenshots/timeline.png)

## Quick start

### Local (Docker Compose)

```bash
git clone https://github.com/HassanFasseh/AI-Operated-Model-Deployment-Platform
cd AI-Operated-Model-Deployment-Platform
cp .env.example .env
# Add your API keys to .env
docker compose up
```

Open `http://localhost:8000/dashboard`

### Production (Kubernetes on Oracle Cloud Always Free)

Requirements: Oracle Cloud account, Terraform, kubectl, Docker with buildx

```bash
cd terraform
terraform init
terraform apply
```

Then configure your GitHub Actions secrets and push — CI/CD handles the rest.

## API reference

### Authenticated prediction

```bash
curl -X POST http://your-platform/api/v1/predict \
  -H "X-API-Key: aodp_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"text": "your input here", "model_id": 1}'
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

### Upload your own model

```bash
curl -X POST http://your-platform/api/v1/upload-model \
  -H "X-API-Key: aodp_your_key_here" \
  -F "file=@my_model.bin" \
  -F "model_name=my-sentiment-v1" \
  -F "workspace_id=1"
```

### Configure automated remediation

```bash
curl -X POST http://your-platform/api/v1/remediations \
  -H "X-API-Key: aodp_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_id": 1,
    "drift_threshold": 0.5,
    "action_type": "github_issue",
    "target": "your-org/your-repo"
  }'
```

When drift crosses the threshold, the platform automatically creates a GitHub issue like this:

![GitHub Issue](docs/screenshots/github-issue.png)

### Request workspace access

```bash
curl -X POST http://your-platform/access-requests \
  -H "Authorization: Bearer your_jwt_token" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": 1,
    "team_id": 1,
    "deployment_id": 2,
    "message": "I need access to the sentiment model for my research project"
  }'
```

## Access control model

```
Organization
  └── Workspace (owned by admin)
        ├── Models (deployed by admin)
        ├── Teams
        │     ├── Team Alpha → access to Model A only
        │     └── Team Beta → access to all models
        └── API Keys (scoped to team + model)
```

![Workspaces](docs/screenshots/workspaces.png)

**Flow:**
1. Admin deploys a model and documents it with a model card
2. Admin creates teams and assigns which models each team can access
3. Users request access — admin approves or denies
4. Approved users get API keys scoped to their team's permitted models
5. Every prediction is attributed to a workspace

## Models currently deployed

| Model | Task | Source |
|---|---|---|
| distilbert-base-uncased-finetuned-sst-2-english | Sentiment analysis | HuggingFace |
| valhalla/distilbart-mnli-12-1 | Zero-shot classification | HuggingFace |
| cardiffnlp/twitter-roberta-base-sentiment-latest | Twitter sentiment (3-class) | HuggingFace |
| cardiffnlp/twitter-roberta-base-sentiment | Twitter sentiment | HuggingFace |

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | Kubernetes (OKE, ARM64, Always Free) |
| Infrastructure | Terraform, Oracle Cloud |
| CI/CD | GitHub Actions (multi-arch buildx) |
| Model serving | FastAPI, HuggingFace Transformers |
| Monitoring | Prometheus, Grafana, kube-prometheus-stack |
| Drift detection | Evidently AI 0.7.21, Redis |
| LLM explanation | Groq (openai/gpt-oss-20b), Gemini Flash fallback |
| Auth | JWT (python-jose), bcrypt |
| Database | PostgreSQL, Alembic migrations |
| Object storage | MinIO (S3-compatible) |
| Local dev | Docker Compose |

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key for LLM summaries |
| `GEMINI_API_KEY` | Google AI Studio key (Gemini Flash fallback) |
| `GITHUB_TOKEN` | Fine-grained PAT with Actions + Issues write |
| `GITHUB_REPO` | Your repo in `owner/repo` format |

## Honest limitations

- **Single-node cluster** — Oracle Always Free provides one ARM64 VM. For production, use a multi-node cluster.
- **Public dashboard** — `/dashboard` requires no login. Auth-gated dashboard is on the roadmap.
- **3 LoadBalancer limit** — Oracle Free tier caps at 3. User-deployed models use ClusterIP and are in-cluster only.
- **Drift computed in batches** — drift detection runs every 30 predictions, not continuously. State persists across restarts via Redis.

## Roadmap

- [ ] Dashboard authentication (require workspace login)
- [ ] Frontend for teams and permissions management
- [ ] A/B traffic splitting between model versions
- [ ] Helm chart for one-command deployment
- [ ] Population drift alerts via email/Slack
- [ ] Federated drift signal sharing across organizations (privacy-preserving)
- [ ] GPU node support

## Contributing

Pull requests welcome. Open an issue first for major changes.

```bash
# Run locally
docker compose up

# Run tests
pytest backend/tests/

# Generate a migration after model changes
alembic --config backend/alembic.ini revision --autogenerate -m "description"
```

## License

[Apache 2.0](LICENSE)

## Author

Hassan Fasseh — Data Science & AI Engineering, Morocco
[GitHub](https://github.com/HassanFasseh)