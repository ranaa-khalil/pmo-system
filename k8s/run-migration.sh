#!/usr/bin/env bash
set -euo pipefail

namespace="${1:-pmo-system}"
deployment="${2:-pmo-system}"
image="${3:-}"
job_name="pmo-system-migrate-$(date -u +%Y%m%d%H%M%S)"

if [[ -z "$image" ]]; then
  image="$(kubectl -n "$namespace" get deployment "$deployment" -o jsonpath='{.spec.template.spec.containers[?(@.name=="app")].image}')"
fi

if [[ -z "$image" ]]; then
  echo "Could not resolve the app image from deployment/$deployment in namespace $namespace" >&2
  exit 1
fi

echo "Creating migration job $job_name with image $image"
kubectl create -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${namespace}
  labels:
    app.kubernetes.io/name: pmo-system-migrate
    app.kubernetes.io/part-of: pmo-system
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/name: pmo-system-migrate
        app.kubernetes.io/part-of: pmo-system
      annotations:
        sidecar.istio.io/inject: "false"
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: migrate
          image: ${image}
          imagePullPolicy: IfNotPresent
          command: ["/bin/sh", "-c"]
          args:
            - |
              set -eu
              # Fresh/dev DB bootstrap stays on app.migrate (ADR-04): creates
              # tables, adds missing columns/indexes, seeds reference data.
              python -m app.migrate
              # Stamp-if-needed (R0 baseline, ADR-04): a DB whose schema was
              # built by app.migrate has no alembic_version yet — stamp head
              # so `alembic upgrade` only applies NEW revisions and never
              # re-runs the baseline DDL on a populated schema.
              if ! python -c "
              import os
              from sqlalchemy import create_engine, inspect, text
              engine = create_engine(os.environ['PMO_DATABASE_URL'])
              with engine.connect() as conn:
                  if inspect(conn).has_table('alembic_version') and conn.execute(text('SELECT COUNT(*) FROM alembic_version')).scalar():
                      raise SystemExit(0)
              raise SystemExit(1)
              "; then
                echo 'No alembic_version row — stamping head (existing DB, schema already applied)'
                alembic stamp head
              fi
              alembic upgrade head
          env:
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: pmo-secrets
                  key: postgres-user
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: pmo-secrets
                  key: postgres-password
            - name: POSTGRES_DB
              valueFrom:
                secretKeyRef:
                  name: pmo-secrets
                  key: postgres-database
            - name: PMO_DATABASE_URL
              value: postgresql://\$(POSTGRES_USER):\$(POSTGRES_PASSWORD)@postgres:5432/\$(POSTGRES_DB)
            - name: PMO_ENV
              value: production
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          securityContext:
            runAsUser: 999
            runAsGroup: 999
            runAsNonRoot: true
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
EOF

if ! kubectl -n "$namespace" wait --for=condition=complete "job/$job_name" --timeout=300s; then
  kubectl -n "$namespace" logs "job/$job_name" --all-containers=true || true
  kubectl -n "$namespace" describe "job/$job_name" || true
  exit 1
fi

kubectl -n "$namespace" logs "job/$job_name" --all-containers=true
echo "Migration job $job_name completed successfully"
