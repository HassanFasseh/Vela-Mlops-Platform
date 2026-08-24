# Vela — MLOps Platform

## What this project is
Self-hosted open-source MLOps platform for regulated industries. FastAPI backend, Kubernetes on Oracle Cloud, PostgreSQL, MinIO, Redis.

## Current focus
Building the frontend: admin dashboard, user dashboard, login page, workspace management, ticket system.

## Design system
- Dark theme: background #0a0a0f, cards #111, borders #1e1e2e
- Primary text: #e0e0e0, secondary: #555
- Accent blue: #7eb8f7, green: #7ef7a0, red: #f77e7e, amber: #f7c97e
- Font: monospace throughout
- Border radius: 8px on cards, 4px on inputs
- No external CSS frameworks — vanilla CSS only

## Backend API base URL
http://51.170.140.102

## Key endpoints
- POST /auth/login — {"username": "...", "password": "..."}
- GET /auth/me — returns user with is_admin flag
- POST /auth/change-password
- GET/POST /admin/users
- GET/POST /admin/teams
- POST /admin/teams/{id}/users/{id}
- GET/POST /tickets
- GET /admin/tickets
- PATCH /admin/tickets/{id}
- GET /workspaces
- GET /deployments
- GET /metrics-summary
- GET /summary
- GET /timeline

## Architecture
- All HTML pages served from FastAPI as raw HTML strings
- JS is vanilla, no frameworks
- Auth: JWT stored in localStorage as aodp_token
- API keys: X-API-Key header, prefix aodp_

## What already exists
- Login page at /auth/login-page
- Workspaces page at /workspaces-page
- Workspace dashboard at /workspace/{id}
- Main monitoring dashboard at /dashboard
- Admin endpoints fully built
- Team/permission system fully built
- Ticket system fully built
- PostgreSQL persistent storage
- Alembic migrations

## What needs building
- Landing page (/)
- Admin dashboard (/admin)
- User dashboard (/user-dashboard)
- Force password change page (/change-password)
- Model detail page
