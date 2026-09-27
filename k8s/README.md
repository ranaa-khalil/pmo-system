# Kubernetes deployment

The manifests deploy the PMO application and PostgreSQL into the `pmo-system`
namespace. PostgreSQL uses a 10 Gi Longhorn persistent volume, and application
uploads use a separate 5 Gi Longhorn persistent volume. The application service
is internal to the cluster.

Create the namespace and secret before applying the workloads:

```bash
kubectl apply -f k8s/namespace.yaml
kubectl -n pmo-system create secret generic pmo-secrets \
  --from-literal=postgres-user=pmo \
  --from-literal=postgres-password='<random-password>' \
  --from-literal=postgres-database=pmo_system \
  --from-literal=pmo-secret-key='<random-secret>'
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/app.yaml
kubectl apply -f k8s/virtualservice.yaml
```

Access the application locally:

```bash
kubectl -n pmo-system port-forward service/pmo-system 8000:80
```

Then open <http://localhost:8000>.

The Istio VirtualService exposes the application as
`pmo-system.obelion.ai` through `istio-ingress/cloudgate-gateway`. The shared
gateway must allow that hostname on its HTTP and HTTPS servers.

## Run database migrations

Each application image contains an idempotent migration command:

```bash
python -m app.migrate
```

For Kubernetes, run the helper before deploying a new application image:

```bash
./k8s/run-migration.sh
```

The helper reads the image from the live `pmo-system` Deployment, creates a
uniquely named Job in the `pmo-system` namespace, waits for completion, and
prints its logs. The Job gets database credentials from `pmo-secrets`, disables
Istio sidecar injection, and is automatically deleted one hour after finishing.

To target a different namespace or Deployment:

```bash
./k8s/run-migration.sh <namespace> <deployment-name>
```

To migrate with a newly published image before updating the Deployment:

```bash
./k8s/run-migration.sh pmo-system pmo-system paulahakeem/pmo-system:sha-<commit>
```
