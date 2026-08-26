{{/*
Vault Agent Injector annotations for a pod template's metadata.annotations.

Include under `spec.template.metadata.annotations` on a Deployment, guarded
by the same condition used in that Deployment's container spec:

    {{- if and (eq .Values.secrets.backend "vault") .Values.secrets.vault.enabled }}
    annotations:
      {{- include "vela.vaultAnnotations" . | nindent 8 }}
    {{- end }}

The Injector (a mutating admission webhook watching for these annotations)
adds a Vault Agent init container + sidecar to the pod. The init container
authenticates via Kubernetes auth — the pod's ServiceAccount token plus
`secrets.vault.role` — reads the KV v2 secret at `secrets.vault.path`, and
renders it to /vault/secrets/config as shell-sourceable `export KEY="value"`
lines (via the custom template below) before the main container starts. The
sidecar then keeps that file fresh for the pod's lifetime.

See the consuming Deployment for how /vault/secrets/config actually reaches
the app's environment (short version: `. /vault/secrets/config` before
exec'ing the real entrypoint).
*/}}
{{- define "vela.vaultAnnotations" -}}
vault.hashicorp.com/agent-inject: "true"
vault.hashicorp.com/role: {{ .Values.secrets.vault.role | quote }}
vault.hashicorp.com/agent-inject-secret-config: {{ .Values.secrets.vault.path | quote }}
vault.hashicorp.com/tls-skip-verify: {{ .Values.secrets.vault.tlsSkipVerify | quote }}
{{- if .Values.secrets.vault.address }}
vault.hashicorp.com/service: {{ .Values.secrets.vault.address | quote }}
{{- end }}
{{/*
Default Agent-inject rendering is a JSON dump of the KV entry — not directly
usable as env vars. This companion "agent-inject-template-<name>" annotation
(same <name> = "config" as the -secret-config annotation above, which is how
the Injector pairs a secret with its template) overrides that with the
standard HashiCorp-documented "environment variable style" template: iterate
every key in the KV entry's data map and print it as an `export KEY="value"`
line. Whatever keys exist at secrets.vault.path get exported — no fixed key
list to keep in sync here.

The lines below are Vault Agent's own (consul-template-flavored) template
syntax, not Helm's — wrapped in backtick raw strings so Helm's template
engine emits them as literal text instead of trying to evaluate them itself.
*/}}
vault.hashicorp.com/agent-inject-template-config: |
{{ printf `  {{- with secret "%s" -}}
  {{- range $k, $v := .Data.data }}
  export {{ $k }}="{{ $v }}"
  {{- end }}
  {{- end }}` .Values.secrets.vault.path }}
{{- end }}
