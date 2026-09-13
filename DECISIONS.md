# Decisions

Notable tradeoffs made in this codebase, and why.

## Admin LLM provider key: encrypted-at-rest, not env/secrets-manager-only

The admin-configurable LLM provider (`backend/app/services/llm_provider.py`,
`LLMProviderConfig` in `db/models.py`) stores the provider API key in the
database, encrypted with Fernet. The encryption key is derived from the
existing `SECRET_KEY` env var (already used for JWT signing in
`services/auth.py`) rather than a dedicated secret - so this ships with no
new required configuration, and a self-service admin can set/change the
provider from the Settings UI without a redeploy or infra access.

The tradeoff: this is DB-encrypted-at-rest, not a real secrets manager.
Anyone with `SECRET_KEY` and DB access can decrypt the stored key. That's an
acceptable bar for a self-service admin UX, but **a hardened production
deploy should not rely on this alone** - set a distinct, properly-managed
`SECRET_KEY` at minimum, and consider keeping the LLM provider key in an
env var or a real secrets manager (Vault, cloud KMS, k8s Secret mounted as
a file) instead of DB storage entirely, wiring `services/llm_provider.py`
to read from there rather than the `llm_provider_config` table.
