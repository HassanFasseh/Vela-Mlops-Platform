{{/*
Base chart name.
*/}}
{{- define "vela.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name.
*/}}
{{- define "vela.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name and version, for the chart label.
*/}}
{{- define "vela.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Namespace to render resources into.
*/}}
{{- define "vela.namespace" -}}
{{- default .Release.Namespace .Values.namespaceOverride }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "vela.labels" -}}
helm.sh/chart: {{ include "vela.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: vela
{{- end }}

{{/*
Full image reference: registry.repository/image:tag
*/}}
{{- define "vela.image" -}}
{{- printf "%s/%s:%s" .root.Values.registry.repository .repository .tag }}
{{- end }}

{{/*
DATABASE_URL, derived unless database.urlOverride is set.
*/}}
{{- define "vela.databaseUrl" -}}
{{- if .Values.database.urlOverride }}
{{- .Values.database.urlOverride }}
{{- else }}
{{- printf "postgresql://%s:%s@postgres:5432/%s" .Values.database.user .Values.database.password .Values.database.name }}
{{- end }}
{{- end }}
