# AI-Operated Model Deployment Platform

> Self-hosted, privacy-first MLOps platform. Deploy any HuggingFace model as a live API, monitor it continuously, detect drift, and get plain-language explanations — without sending a byte of data outside your infrastructure.

[SCREENSHOT: dashboard overview showing live metrics, drift score 1.000, population-level breakdown panel, and LLM summary]

## Why this exists

Most ML tools solve the training problem. This solves the operations problem — what happens after a model is deployed, when nobody is watching, and the world keeps changing.

Organizations with data privacy requirements — hospitals, banks, universities, government agencies — cannot send data to HuggingFace Spaces or cloud ML services. This platform runs entirely on your own infrastructure. Apache 2.0 licensed.

## What it does

**Deploy** — Submit a HuggingFace model name through the dashboard. GitHub Actions builds a multi-arch Docker image, pushes it to your registry, and deploys it to Kubernetes. Live in 5–10 minutes.

**Monitor** — Prometheus scrapes metrics every 15 seconds. Evidently AI computes drift across a sliding window, comparing the current input distribution against a reference baseline. Redis persists state across restarts.

**Explain** — When drift is detected, the platform identifies which specific signals shifted (confidence score, label distribution, input length) and generates a plain-language summary via Groq or Gemini Flash. Not just "drift detected" — "your confidence score and label distribution have both shifted significantly since the deploy 2 hours ago."

**Act** — When drift crosses a configured threshold, the platform automatically opens a GitHub issue, fires a webhook, or triggers a retraining pipeline. No human needs to notice and react.

**Control** — Multi-tenant workspaces with JWT auth. Teams with role-based model permissions. Access request and approval flow. API keys scoped to specific teams and models.

[SCREENSHOT: workspace dashboard showing API keys, members list, and model card form]

## Live demo

- Dashboard: `http://51.170.140.102/dashboard`
- Auth: `http://51.170.140.102/auth/login-page`
- Grafana: `http://51.170.129.103`

## Architecture

┌─────────────────────────────────────────────────────────────┐
│ Deployment loop │
│ Dashboard form → GitHub Actions → Docker build → OKE deploy│
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ Operations loop (continuous) │
│ Prometheus scrape → Evidently drift → Event correlation │
│ → Groq/Gemini LLM summary → Dashboard auto-refresh 30s │
└─────────────────────────────────────────────────────────────┘

[SCREENSHOT: operations timeline showing deploy events, drift spikes, and latency readings]

## Quick start

### Local (Docker Compose)

```bash
git clone https://github.com/HassanFasseh/AI-Operated-Model-Deployment-Platform
cd AI-Operated-Model-Deployment-Platform
cp .env.example .env
# Add your GROQ_API_KEY and GEMINI_API_KEY to .env
docker compose up
```

Open `http://localhost:8000/dashboard`

### Production (Kubernetes on Oracle Cloud)

Requirements: Oracle Cloud account, Terraform, kubectl, Docker with buildx

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Fill in your OCI credentials
terraform init && terraform apply
```

See [deployment guide](docs/deployment.md) for the full setup.

## API reference

### Predict (authenticated)

```bash
curl -X POST https://your-platform/api/v1/predict \
  -H "X-API-Key: aodp_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"text": "your input here", "model_id": 1}'
```

Response:
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
curl -X POST https://your-platform/api/v1/upload-model \
  -H "X-API-Key: aodp_your_key_here" \
  -F "file=@my_model.bin" \
  -F "model_name=my-sentiment-v1" \
  -F "workspace_id=1"
```

### Configure remediation

```bash
curl -X POST https://your-platform/api/v1/remediations \
  -H "X-API-Key: aodp_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_id": 1,
    "drift_threshold": 0.5,
    "action_type": "github_issue",
    "target": "your-org/your-repo"
  }'
```

[SCREENSHOT: GitHub issue automatically created by the platform showing drift alert with specific column details]

## Models currently deployed

| Model | Task | Source |
|---|---|---|
| distilbert-base-uncased-finetuned-sst-2-english | Sentiment analysis | HuggingFace |
| valhalla/distilbart-mnli-12-1 | Zero-shot classification | HuggingFace |
| cardiffnlp/twitter-roberta-base-sentiment-latest | Twitter sentiment | HuggingFace |
| cardiffnlp/twitter-roberta-base-sentiment | Twitter sentiment | HuggingFace |

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | Kubernetes (OKE, ARM64) |
| Infrastructure | Terraform, Oracle Cloud Always Free |
| CI/CD | GitHub Actions (multi-arch buildx) |
| Model serving | FastAPI, HuggingFace Transformers |
| Monitoring | Prometheus, Grafana, kube-prometheus-stack |
| Drift detection | Evidently AI 0.7.21, Redis |
| LLM explanation | Groq (openai/gpt-oss-20b), Gemini Flash fallback |
| Auth | JWT (python-jose), bcrypt |
| Database | PostgreSQL, Alembic migrations |
| Object storage | MinIO (S3-compatible) |
| Local dev | Docker Compose |

## Workspace and access control

[SCREENSHOT: workspaces page showing list of workspaces]

Teams are isolated workspaces. Each team gets:
- Their own deployed models
- Role-based members (admin / member / viewer)
- API keys scoped to specific models
- Model cards documenting datasets, licenses, and limitations

Users can request access to a workspace or team. Admins approve or deny requests. Approved users are automatically added to the workspace and team.

## Honest limitations

- **Drift detection resets on pod restart** unless Redis is available (which it is in the default deployment)
- **Single-node cluster** on Oracle Cloud Always Free — not suitable for high-availability production. Swap to a multi-node cluster for production use.
- **No authentication on the main dashboard** — the `/dashboard` endpoint is currently public. Planned for Phase 2.
- **LoadBalancer limit** — Oracle Free tier caps at 3 load balancers. User-deployed models use ClusterIP and are accessible in-cluster only.

## Roadmap

- [ ] Dashboard authentication (require login to view)
- [ ] Frontend for teams and permissions management
- [ ] A/B traffic splitting between model versions
- [ ] Federated drift signal sharing across organizations
- [ ] Helm chart for one-command deployment
- [ ] GPU node support

## License

Apache 2.0 — see [LICENSE](LICENSE)

## Author

Hassan Fasseh — Data Science & AI Engineering student, Morocco
[GitHub](https://github.com/HassanFasseh) · [LinkedIn](your-linkedin)