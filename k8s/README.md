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
