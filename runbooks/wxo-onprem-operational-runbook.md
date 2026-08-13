# watsonx Orchestrate On-Premises — Operational Runbook

**Product:** IBM watsonx Orchestrate  
**Deployment:** On-Premises (IBM Software Hub / Cloud Pak for Data)  
**Audience:** Cluster Administrators, Platform Operators  
**Versions:** 5.2.x – 5.4.x+

---

## Overview

This runbook documents procedures for diagnosing and resolving common operational issues in watsonx Orchestrate on-premises deployments. It covers:

- [Collecting diagnostic logs](#collecting-diagnostic-logs)
- [Checking the health of your deployment](#checking-deployment-health)
- [UI inaccessible or showing errors](#ui-inaccessible-or-showing-errors)
- [Skills not working](#skills-not-working)
- [Skill catalog or Skill Studio not loading](#skill-catalog-or-skill-studio-not-loading)
- [PostgreSQL connection pool exhaustion](#postgresql-connection-pool-exhaustion)
- [Installation deadlock — stuck at 78%](#installation-deadlock--stuck-at-78)
- [Milvus standalone crashing — etcd space exceeded](#milvus-standalone-crashing--etcd-space-exceeded)
- [Post-upgrade user management failures](#post-upgrade-user-management-failures)
- [Restarting watsonx Orchestrate deployments in the correct order](#restarting-watsonx-orchestrate-deployments-in-the-correct-order)
- [ClickHouse and Langfuse issues (5.4+)](#clickhouse-and-langfuse-issues-54)
- [EDB operator CrashLoopBackOff — missing RBAC rules](#edb-operator-crashloopbackoff--missing-rbac-rules)
- [Kafka timeout configuration](#kafka-timeout-configuration)
- [Nginx proxy buffer and timeout patching](#nginx-proxy-buffer-and-timeout-patching)
- [Observability enablement and cleanup (5.4.x)](#observability-enablement-and-cleanup-54x)
- [Python tools in air-gapped environments (ADK)](#python-tools-in-air-gapped-environments-adk)

---

## Prerequisites

- OpenShift CLI (`oc`) installed and logged in with cluster-admin privileges
- Access to the IBM Software Hub operand namespace (commonly `cpd`, `cpd-instance`, or a custom name)
- The following environment variables set before running any commands:

```bash
export PROJECT_CPD_INST_OPERANDS=<your-operand-namespace>   # e.g. cpd
export PROJECT_CPD_INST_OPERATORS=<your-operator-namespace>  # e.g. cpd-operators
```

---

## Collecting Diagnostic Logs

Before troubleshooting, collect logs using IBM Software Hub's built-in Diagnostics capability.

### Using the IBM Software Hub UI

1. Log in to IBM Software Hub. From the left navigation menu, go to **Support → Diagnostics**.
2. Click **New diagnostics job**.
3. Select the service: **watsonx Orchestrate**.
4. Configure the time range to match when the issue occurred.
5. Select components:
   - **Tenant instance logs** — logs for the running watsonx Orchestrate tenant.
   - **Foundation service logs** — select **orchestrate** for core service logs.
   - **Cluster configuration** — select **MustgatherLogCollection** for cluster status.
6. Click **Create** and wait for the job to finish (typically 5–15 minutes).
7. Download and unzip the resulting archive.

### Using the CLI

```bash
# Check overall watsonx Orchestrate status
oc get wo -n $PROJECT_CPD_INST_OPERANDS

# Check all pod statuses
oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep -v "Completed\|Running"

# Check for CrashLoopBackOff pods
oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep CrashLoopBackOff

# Get logs for a specific pod
oc logs <pod-name> -n $PROJECT_CPD_INST_OPERANDS --tail=100

# Get previous logs for a crashed pod
oc logs <pod-name> -n $PROJECT_CPD_INST_OPERANDS --previous --tail=100
```

---

## Checking Deployment Health

Use these commands to quickly assess the state of a watsonx Orchestrate deployment.

```bash
# Check the WO CR status
oc get wo -n $PROJECT_CPD_INST_OPERANDS -o yaml | grep -A 10 "status:"

# Check the WO operator version
oc get wo -n $PROJECT_CPD_INST_OPERANDS -o jsonpath='{.items[0].status.versionStatus.status}'

# Check EDB/PostgreSQL cluster
oc get cluster.postgres -n $PROJECT_CPD_INST_OPERANDS

# Check all deployments
oc get deployments -n $PROJECT_CPD_INST_OPERANDS | grep -v "1/1\|2/2\|3/3"

# Check Milvus standalone
oc get deployment ibm-lh-lakehouse-wo-milvus-standalone -n $PROJECT_CPD_INST_OPERANDS
```

---

## UI Inaccessible or Showing Errors

### Symptoms

- Login page returns 404 or access-denied errors
- watsonx Orchestrate home page shows a blank screen
- `build-ui` or UI proxy errors (`/mfe_builder/remoteEntry.js` returning 5xx)
- "Error decoding cache data" on the UI

### Step 1 — Check UI proxy (wo) pod logs

```bash
# Look for upstream errors in the wo (UI proxy) pod
oc logs -n $PROJECT_CPD_INST_OPERANDS \
  $(oc get pods -n $PROJECT_CPD_INST_OPERANDS -l app=wo -o jsonpath='{.items[0].metadata.name}') \
  --tail=100 | grep -i "error\|5[0-9][0-9]\|connection reset\|upstream"
```

Common error patterns and actions:

| Error in logs | Cause | Action |
|---|---|---|
| `connection reset by peer` on `/mfe_builder/remoteEntry.js` | `build-ui` pod unhealthy | Restart `build-ui`, then `wo` |
| `502` / `401` on `/asb/ui-framework/remoteEntry.js` | Agent builder UI proxy issue | Restart `wo` |
| `Error decoding cache data` on `/crn-mapping` | Nginx shared-memory cache corruption | Restart `wo` |

### Step 2 — Restart UI proxy pods

Restart `build-ui` first (if applicable to your version), then `wo`:

```bash
# Restart build-ui (introduced in agentic versions)
oc rollout restart deployment/build-ui -n $PROJECT_CPD_INST_OPERANDS

# Wait for build-ui to become healthy
oc rollout status deployment/build-ui -n $PROJECT_CPD_INST_OPERANDS

# Restart the wo UI proxy
oc rollout restart deployment/wo -n $PROJECT_CPD_INST_OPERANDS

# Wait for wo to become healthy
oc rollout status deployment/wo -n $PROJECT_CPD_INST_OPERANDS
```

### Step 3 — If the UI is still inaccessible after UI proxy restart

Check whether the issue is caused by PostgreSQL connection exhaustion (see [PostgreSQL Connection Pool Exhaustion](#postgresql-connection-pool-exhaustion)).

```bash
# Check active database connections
oc exec -n $PROJECT_CPD_INST_OPERANDS \
  $(oc get pods -n $PROJECT_CPD_INST_OPERANDS -l "k8s.enterprisedb.io/instanceRole=primary" \
    -o jsonpath='{.items[0].metadata.name}') \
  -- psql -U postgres -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state != 'idle';"
```

If the connection count is at or near the configured maximum (default 500 for on-prem), proceed to [PostgreSQL Connection Pool Exhaustion](#postgresql-connection-pool-exhaustion).

---

## Skills Not Working

### Symptoms

- Skills return: *"Working on getting the results — might take a while"*
- Skills run indefinitely without returning a result
- Skill execution silently fails

### Step 1 — Identify the failing component

```bash
# Check de-server and de-client pod logs
oc logs -n $PROJECT_CPD_INST_OPERANDS \
  $(oc get pods -n $PROJECT_CPD_INST_OPERANDS -l app=de-server -o jsonpath='{.items[0].metadata.name}') \
  --tail=50 | grep -i "error\|fail"

oc logs -n $PROJECT_CPD_INST_OPERANDS \
  $(oc get pods -n $PROJECT_CPD_INST_OPERANDS -l app=de-client -o jsonpath='{.items[0].metadata.name}') \
  --tail=50 | grep -i "error\|fail"
```

If you see `NoneType object has no attribute 'get'` or messaging I/O manager errors, the DE (Digital Employee) server–client messaging channel is broken.

### Step 2 — Restart the DE components

Restart `de-client` first, then `de-server` if the issue persists:

```bash
# Restart de-client
oc rollout restart deployment/de-client -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/de-client -n $PROJECT_CPD_INST_OPERANDS

# If skills still fail after de-client restart, restart de-server as well
# Note: restarting de-server causes a brief AMQP connection spike — this is expected
oc rollout restart deployment/de-server -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/de-server -n $PROJECT_CPD_INST_OPERANDS
```

### Step 3 — Verify skills work

After restarting, test a skill invocation. If skills continue to fail, also restart `tenantregistry`:

```bash
oc rollout restart deployment/tenantregistry -n $PROJECT_CPD_INST_OPERANDS
```

---

## Skill Catalog or Skill Studio Not Loading

### Symptoms

- Skill catalog shows: *"Something went wrong"*
- Skill Studio is inaccessible or shows: *"Unexpected Error"*

### Step 1 — Check skill-server logs

```bash
# Look for 400-class errors in skill-server
oc logs -n $PROJECT_CPD_INST_OPERANDS \
  $(oc get pods -n $PROJECT_CPD_INST_OPERANDS -l app=skill-server -o jsonpath='{.items[0].metadata.name}') \
  --tail=50 | grep -i "400\|error\|fail"
```

### Step 2 — Restart skill-server

```bash
oc rollout restart deployment/skill-server -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/skill-server -n $PROJECT_CPD_INST_OPERANDS
```

---

## PostgreSQL Connection Pool Exhaustion

### Symptoms

- UI login fails or is very slow
- Skills return errors or time out
- Pod logs contain errors like:
  ```
  J2CA0045E: Connection not available while invoking method createOrWaitForConnection
  Timed out waiting for 30,000 millisecond(s) with 135 remaining waiting requests and 30 current total connections used.
  ```

### Why this happens

Multiple watsonx Orchestrate services (tenantregistry, tenantcontroller, and others) share a PostgreSQL connection pool managed by Liberty's JPA. Under high load, or after a PostgreSQL failover, stale or exhausted connections accumulate. Liberty JPA does not automatically retry or refresh these connections — a pod restart is required to reset the pool.

### Step 1 — Diagnose connection state

Connect to the primary EDB/PostgreSQL pod and check active connections:

```bash
# Find the primary PostgreSQL pod
PG_PRIMARY=$(oc get pods -n $PROJECT_CPD_INST_OPERANDS \
  -l "k8s.enterprisedb.io/instanceRole=primary" \
  -o jsonpath='{.items[0].metadata.name}')

echo "Primary PostgreSQL pod: $PG_PRIMARY"

# Count all active (non-idle) connections
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -- \
  psql -U postgres -c "SELECT COUNT(*) AS active_connections FROM pg_stat_activity WHERE state != 'idle';"

# Break down connections by application and database
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -- psql -U postgres -c "
SELECT
    datname        AS database,
    usename        AS username,
    application_name,
    client_addr    AS source_ip,
    count(*)       AS connections
FROM pg_stat_activity
WHERE datname IS NOT NULL
GROUP BY datname, usename, application_name, client_addr
ORDER BY connections DESC;"
```

The output shows which services are consuming the most connections. Services with hundreds of connections are the primary consumers to restart.

### Step 2 — Restart the high-connection services

Restart in this order to minimise cascading effects:

```bash
# 1. Restart api-server-runs and archer-server to free DB connections quickly
oc rollout restart deployment/api-server-runs -n $PROJECT_CPD_INST_OPERANDS
oc rollout restart deployment/archer-server -n $PROJECT_CPD_INST_OPERANDS

# Wait for them to stabilise (30–60 seconds), then check connection count again
sleep 60

# 2. Once connections drop, restart tenantregistry
oc rollout restart deployment/tenantregistry -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/tenantregistry -n $PROJECT_CPD_INST_OPERANDS
```

### Step 3 — Verify recovery

```bash
# Confirm active connections have dropped
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -- \
  psql -U postgres -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state != 'idle';"

# Clear browser cookies and retry logging in
```

### Preventive recommendation

The default PostgreSQL `max_connections` for on-premises deployments may be set conservatively (typically 300–500). If your deployment has many concurrent users or tenants, consider increasing this value. Contact IBM Support to review the appropriate value for your workload.

---

## Installation Deadlock — Stuck at 78%

### Symptoms

- `oc get wo -n $PROJECT_CPD_INST_OPERANDS` shows `STATUS: InProgress` for more than 2 hours
- Multiple pods in `CrashLoopBackOff` with 60+ restarts:
  - `wo-tools-runtime-manager`
  - `wo-wxo-connections`
- Pod logs contain:
  ```
  pq: database "tools_runtime" does not exist
  pq: database "wxo_connections" does not exist
  ```
- Job `wo-watson-orchestrate-pg-init-onprem` has exceeded its backoff limit

### Root cause

The PostgreSQL database initialisation job fires 150+ concurrent `CREATE DATABASE` / `CREATE SCHEMA` operations. These deadlock against each other. When the job fails, pgbouncer (the connection pooler) caches the failure and continues rejecting new connections even after PostgreSQL recovers — requiring a pgbouncer restart as a separate step.

### Step 1 — Confirm the deadlock

```bash
# Check PostgreSQL active queries
PG_PRIMARY=$(oc get pods -n $PROJECT_CPD_INST_OPERANDS \
  -l "k8s.enterprisedb.io/instanceRole=primary" \
  -o jsonpath='{.items[0].metadata.name}')

oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -- psql -U postgres -c "
SELECT pid, usename, application_name, state, wait_event_type, wait_event, left(query,80) AS query
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY query_start;"

# Check if target databases are missing
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -- psql -U postgres -c "
SELECT datname FROM pg_database WHERE datname IN ('tools_runtime', 'wxo_connections');"
```

### Step 2 — Kill the blocking queries

```bash
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -- psql -U postgres -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state != 'idle'
  AND pid != pg_backend_pid()
  AND query NOT LIKE '%pg_stat_activity%';"
```

### Step 3 — Delete and wait for PostgreSQL pods to recover

```bash
# Delete PostgreSQL pods (they will be recreated by the EDB operator)
for pod in $(oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep postgresedb | awk '{print $1}'); do
  oc delete pod $pod -n $PROJECT_CPD_INST_OPERANDS --force --grace-period=0
done

# Wait for the cluster to report 3/3 healthy (takes 2–5 minutes)
watch -n 10 'oc get cluster.postgres -n '$PROJECT_CPD_INST_OPERANDS
```

### Step 4 — Restart pgbouncer (critical — do not skip)

pgbouncer caches the "server login has been failing" error. Even after PostgreSQL recovers, connections fail until pgbouncer pods are restarted.

```bash
for pod in $(oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep pgbouncer | awk '{print $1}'); do
  oc delete pod $pod -n $PROJECT_CPD_INST_OPERANDS
done
```

### Step 5 — Re-trigger the database initialisation job

```bash
# Delete the failed job
oc delete job wo-watson-orchestrate-pg-init-onprem -n $PROJECT_CPD_INST_OPERANDS

# Wait 30 seconds for the operator to recreate it
sleep 30

# Monitor the new job
NEW_POD=$(oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep pg-init-onprem | grep -v Completed | awk '{print $1}')
oc logs -f $NEW_POD -n $PROJECT_CPD_INST_OPERANDS
```

### Step 6 — Verify databases exist and installation resumes

```bash
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -- psql -U postgres -c "
SELECT datname FROM pg_database WHERE datname IN ('tools_runtime', 'wxo_connections');"

# Monitor WO installation status
watch -n 30 'oc get wo -n '$PROJECT_CPD_INST_OPERANDS
```

**Expected:** Both databases appear, crashing pods transition to `Running`, and installation progresses past 78%.

---

## Milvus Standalone Crashing — etcd Space Exceeded

### Symptoms

- `ibm-lh-lakehouse-wo-milvus-standalone` deployment shows `0/1` available
- Pod is in `CrashLoopBackOff` or `ProgressDeadlineExceeded`
- Pod logs contain:
  ```
  panic: etcdserver: mvcc: database space exceeded
  Session Txn failed ... error="etcdserver: mvcc: database space exceeded"
  ```
- Knowledge-base features (agent knowledge, document search) are unavailable

### Root cause

Milvus uses a dedicated etcd instance to store session metadata. When accumulated metadata exceeds the etcd backend quota (2 GiB by default), etcd raises a `NOSPACE` alarm and rejects all write transactions. Milvus cannot start until the alarm is cleared — increasing the PVC size alone does not resolve this.

### Step 1 — Confirm the etcd alarm

```bash
MILVUS_NS=$PROJECT_CPD_INST_OPERANDS   # or the namespace where Milvus is deployed

oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl endpoint status -w table'

oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl alarm list'
```

If `alarm list` shows `NOSPACE`, proceed with the recovery steps below.

### Step 2 — Get the current etcd revision

```bash
oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl endpoint status -w json' | grep -o '"revision":[0-9]*' | head -1
```

Note the revision number (for example: `8665779`).

### Step 3 — Compact the etcd history

Replace `<REVISION>` with the value from Step 2:

```bash
oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl compact <REVISION>'
```

### Step 4 — Defragment the etcd database

Defragmentation reclaims the space freed by compaction. It can take 2–3 minutes:

```bash
oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl --command-timeout=120s defrag'
```

### Step 5 — Disarm the NOSPACE alarm

```bash
oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl --command-timeout=120s alarm disarm'

# Verify no alarms remain
oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl alarm list'
```

### Step 6 — Restart the Milvus standalone pod

```bash
oc rollout restart deployment/ibm-lh-lakehouse-wo-milvus-standalone -n $MILVUS_NS
oc rollout status deployment/ibm-lh-lakehouse-wo-milvus-standalone -n $MILVUS_NS
```

During restart, you may see `node not match` warnings in Milvus logs — these are transient and clear on their own.

### Prevention

To prevent recurrence, consider running compaction and defragmentation periodically (for example, monthly) as part of your maintenance schedule:

```bash
# Scheduled maintenance — run as a cron job or manually during a maintenance window
REVISION=$(oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl endpoint status -w json' | grep -o '"revision":[0-9]*' | head -1 | cut -d: -f2)

oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  "ETCDCTL_API=3 etcdctl compact $REVISION"

oc exec -n $MILVUS_NS ibm-lh-lakehouse-wo-milvus-etcd-0 -- sh -lc \
  'ETCDCTL_API=3 etcdctl --command-timeout=120s defrag'
```

---

## Post-Upgrade User Management Failures

### Symptoms

After upgrading from version 5.2.x to 5.3.x (which enables TLS), user management operations fail:

- Adding, modifying, or deleting users fails silently or with an error
- `tenantregistry` errors in logs:
  ```
  Post "http://wo-tenant-registry.cpd.svc:8080/tenantregistry/api/v1/grant/":
  dial tcp: lookup wo-tenant-registry.cpd.svc: no such host
  ```

### Root cause

The upgrade from 5.2.x to 5.3.x changes the service URL scheme from HTTP to HTTPS (TLS is enabled). The Zen platform database (`add_ons` table) contains stale HTTP URLs pointing to the old non-TLS service endpoints. These must be updated to reflect the new HTTPS endpoints.

### Step 1 — Set up variables

```bash
export PROJECT_CPD_INST_OPERANDS=<your-operand-namespace>

ZEN_HOST=$(oc get secret zen-metastore-edb-app -n $PROJECT_CPD_INST_OPERANDS \
  -o jsonpath='{.data.host}' | base64 -d)

ZEN_PASS=$(oc get secret zen-metastore-edb-app -n $PROJECT_CPD_INST_OPERANDS \
  -o jsonpath='{.data.password}' | base64 -d)

TLS_ENABLED=$(oc get wo wo -n $PROJECT_CPD_INST_OPERANDS \
  -o jsonpath='{.spec.tls.enabled}')
echo "TLS enabled: $TLS_ENABLED"

# Set protocol based on TLS status
PROTOCOL="https"   # Use "http" if TLS_ENABLED is false

ARCHER_SVC=$(oc get svc wo-archer-server -n $PROJECT_CPD_INST_OPERANDS \
  -o jsonpath='{.metadata.name}.{.metadata.namespace}.svc:{.spec.ports[0].port}')
export ARCHER_SERVER_URL="${PROTOCOL}://${ARCHER_SVC}/api/v1/lite/"

echo "Archer URL: $ARCHER_SERVER_URL"
```

### Step 2 — Find stale entries in the Zen database

```bash
POD_NAME=$(oc get pods -n $PROJECT_CPD_INST_OPERANDS \
  -l "k8s.enterprisedb.io/cluster=zen-metastore-edb,k8s.enterprisedb.io/instanceRole=primary" \
  -o jsonpath='{.items[0].metadata.name}')

oc exec $POD_NAME -n $PROJECT_CPD_INST_OPERANDS -- bash -c "
PGPASSWORD=\"$ZEN_PASS\" psql -h \"$ZEN_HOST\" -U zen_user -d zen -t -A -c \"
SELECT id, version, details ->> 'service_provider_url' AS service_provider_url
FROM add_ons
WHERE (details ->> 'service_provider_url' ILIKE '%tenant-registry%'
   OR details ->> 'service_provider_url' ILIKE '%archer-server%')
  AND details ->> 'service_provider_url' != '$ARCHER_SERVER_URL';
\""
```

If any rows are returned, they have stale URLs that must be updated.

### Step 3 — Back up the add_ons table

Always create a backup before modifying platform database tables:

```bash
oc exec $POD_NAME -n $PROJECT_CPD_INST_OPERANDS -- bash -c "
PGPASSWORD=\"$ZEN_PASS\" psql -h \"$ZEN_HOST\" -U zen_user -d zen -c \"
CREATE TABLE add_ons_bkp AS SELECT * FROM add_ons;\""
```

### Step 4 — Update the stale URLs

Contact IBM Support to obtain the correct update SQL for your specific version and deployment configuration. Provide the output of Step 2 when opening the support case.

**Note:** Modifying platform database tables without IBM guidance may cause further issues. Always open a support case and share the diagnostic output before performing Step 4.

---

## Restarting watsonx Orchestrate Deployments in the Correct Order

### When to use this procedure

After an OpenShift Container Platform (OCP) upgrade, or after a Postgres failover, watsonx Orchestrate services may fail to reconnect to dependencies. Restarting services in an arbitrary order can cause cascading failures because some services depend on others being healthy first.

### Correct restart order

Always restart in the following sequence, waiting for each deployment to reach `Ready` before proceeding to the next:

```bash
# Step 1 — tenantregistry
oc rollout restart deployment/tenantregistry -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/tenantregistry -n $PROJECT_CPD_INST_OPERANDS

# Step 2 — tenantcontroller
oc rollout restart deployment/tenantcontroller -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/tenantcontroller -n $PROJECT_CPD_INST_OPERANDS

# Step 3 — wo-api
oc rollout restart deployment/wo-api -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/wo-api -n $PROJECT_CPD_INST_OPERANDS

# Step 4 — wo (UI proxy)
oc rollout restart deployment/wo -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/wo -n $PROJECT_CPD_INST_OPERANDS

# Step 5 — api-server-runs
oc rollout restart deployment/api-server-runs -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/api-server-runs -n $PROJECT_CPD_INST_OPERANDS

# Step 6 — conversation-controller
oc rollout restart deployment/conversation-controller -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/conversation-controller -n $PROJECT_CPD_INST_OPERANDS

# Step 7 — archer-server
oc rollout restart deployment/archer-server -n $PROJECT_CPD_INST_OPERANDS
oc rollout status deployment/archer-server -n $PROJECT_CPD_INST_OPERANDS
```

### Full ordered restart script

Save and run this script for a complete ordered restart:

```bash
#!/usr/bin/env bash
set -euo pipefail

NS="${PROJECT_CPD_INST_OPERANDS:?Set PROJECT_CPD_INST_OPERANDS before running this script}"

DEPLOYMENTS=(
  "tenantregistry"
  "tenantcontroller"
  "wo-api"
  "wo"
  "api-server-runs"
  "conversation-controller"
  "archer-server"
)

for deploy in "${DEPLOYMENTS[@]}"; do
  echo "Restarting $deploy ..."
  oc rollout restart deployment/"$deploy" -n "$NS"
  oc rollout status deployment/"$deploy" -n "$NS"
  echo "  ✓ $deploy is ready"
  echo
done

echo "All deployments restarted successfully."
```

---

## ClickHouse and Langfuse Issues (5.4+)

> **Applies to:** watsonx Orchestrate 5.4.0 and later (agentic edition).
> ClickHouse is the columnar analytics database that backs the Langfuse LLM observability stack. It is deployed alongside watsonx Orchestrate when the observability add-on is enabled.

**Namespace:** `$PROJECT_CPD_INST_OPERANDS` (on-prem; the ClickHouse pods share the watsonx Orchestrate operand namespace)
**Key pods:**

| Pod | Role |
|---|---|
| `chi-application-default-shard-1-0-0` | ClickHouse shard 1 replica 0 |
| `chi-application-default-shard-1-1-0` | ClickHouse shard 1 replica 1 |
| `chk-keeper-application-keeper-0-{0,1,2}-0` | ClickHouse Keeper (3-node quorum) |
| `wo-lf-web-*` | Langfuse web / Prisma migration runner |
| `wo-lf-worker-*` | Langfuse background worker |
| `wo-wxo-observability-*` | Archer observability service |

---

### Issue 1 — `wo-lf-web` CrashLoopBackOff: Prisma Migration Deadlock

#### Symptoms

- `wo-lf-web-*` pods in `CrashLoopBackOff` (20+ restarts)
- Pod exits immediately on every restart with error `P3009`
- `wo-lf-worker` is running fine — only `lf-web` is affected
- Installation is stuck at approximately 84% (`InProgress`)

```
Error: P3009
migrate found failed migrations in the target database, new migrations will not be applied.
The `20240104210051_add_model_indices` migration started at <timestamp> failed
```

#### Root cause

Both `wo-lf-web` and `wo-lf-worker` run `prisma migrate deploy` at startup and race to apply the same migration concurrently. PostgreSQL detects a deadlock (`40P01`) between the two processes competing for an advisory lock. The DDL (creating index `observations_model_idx`) **actually completes** before the deadlock is detected, but Prisma never writes `finished_at` into `_prisma_migrations`, leaving the row in a permanently failed state. On every subsequent restart, Prisma sees the unresolved row and exits immediately.

#### Step 1 — Confirm the failed migration row and verify the index exists

```bash
PG_PRIMARY=$(oc get pods -n $PROJECT_CPD_INST_OPERANDS \
  -l "k8s.enterprisedb.io/instanceRole=primary" \
  -o jsonpath='{.items[0].metadata.name}')

# Show the stuck migration row
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -c postgres -- \
  psql -U postgres -d langfuse -c \
  "SELECT migration_name, started_at, finished_at, rolled_back_at
   FROM _prisma_migrations
   WHERE finished_at IS NULL AND rolled_back_at IS NULL
   ORDER BY started_at DESC LIMIT 5;"

# Confirm the index was actually created (must return a row before proceeding)
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -c postgres -- \
  psql -U postgres -d langfuse -c \
  "SELECT indexname FROM pg_indexes WHERE indexname = 'observations_model_idx';"
```

> **Important:** Only mark a migration as applied after confirming the object it creates exists in the database. Do not blindly mark incomplete migrations as done.

#### Step 2 — Scale `wo-lf-web` down to stop the crash loop

```bash
oc scale deployment wo-lf-web -n $PROJECT_CPD_INST_OPERANDS --replicas=0
oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep lf-web   # expect no pods
```

#### Step 3 — Mark the failed migration as successfully applied

```bash
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -c postgres -- \
  psql -U postgres -d langfuse -c \
  "UPDATE _prisma_migrations
   SET finished_at = now(), applied_steps_count = 1,
       rolled_back_at = NULL, logs = NULL
   WHERE migration_name = '20240104210051_add_model_indices'
     AND finished_at IS NULL;"
```

#### Step 4 — Scale `wo-lf-web` back up

```bash
oc scale deployment wo-lf-web -n $PROJECT_CPD_INST_OPERANDS --replicas=1
oc rollout status deployment/wo-lf-web -n $PROJECT_CPD_INST_OPERANDS
```

#### Step 5 — Verify recovery

```bash
# Pod logs should contain "No pending migrations to apply."
oc logs -n $PROJECT_CPD_INST_OPERANDS \
  $(oc get pods -n $PROJECT_CPD_INST_OPERANDS -l app=wo-lf-web \
    -o jsonpath='{.items[0].metadata.name}') --tail=30

# Confirm no more stuck migration rows
oc exec -n $PROJECT_CPD_INST_OPERANDS $PG_PRIMARY -c postgres -- \
  psql -U postgres -d langfuse -c \
  "SELECT migration_name FROM _prisma_migrations
   WHERE finished_at IS NULL AND rolled_back_at IS NULL;"
```

---

### Issue 2 — `wo-wxo-observability` CrashLoopBackOff: ClickHouse Schema Not Initialised

#### Symptoms

- `wo-wxo-observability-*` pod in `CrashLoopBackOff` (20+ restarts)
- Startup probe failing with `connection refused` on port 4321
- Pod logs contain:

```
ClickHouseSchemaSetupError: ClickHouse add column agentops_tenant_id on
default.traces failed (status=404):
Code: 60. DB::Exception: Could not find table: traces. (UNKNOWN_TABLE)
```

#### Root cause

The `ClickHouseInstallation` CR provisioned its pods but never initialised the `default` database schema (tables such as `traces`, `observations`, `scores`). The `wo-wxo-observability` service tries to run `ALTER TABLE default.traces ADD COLUMN ...` at startup and crashes fatally when the table does not exist.

> **Note:** The ClickHouse database name is **`default`**, not `langfuse`. All Langfuse/observability tables live in the `default` database.

#### Step 1 — Confirm the schema is missing

```bash
# If this returns no rows, the schema was never initialised
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT name FROM system.tables WHERE database='default' FORMAT TabSeparated"

# Also check ClickHouseInstallation CR status
oc get clickhouseinstallation -n $PROJECT_CPD_INST_OPERANDS
```

#### Step 2 — Delete the ClickHouseInstallation CR to force recreation

The ClickHouse Operator recreates the CR, pods, and runs schema initialisation automatically. The ClickHouseKeeper pods (`chk-keeper-application-keeper-*`) remain running and preserve replication state.

> **Warning:** Any existing observability trace data stored in ClickHouse will be lost. This is acceptable for observability data but confirm with your team before proceeding.

```bash
oc delete clickhouseinstallation application -n $PROJECT_CPD_INST_OPERANDS

# Monitor recreation — wait for STATUS: Completed and HOSTS-COMPLETED = 2
oc get clickhouseinstallation application -n $PROJECT_CPD_INST_OPERANDS -w
```

Once both shards are `2/2 Running`, `wo-wxo-observability` recovers automatically on its next restart.

---

### Issue 3 — Langfuse Dirty Migration State: `langfuse-web` in CrashLoopBackOff

#### Symptoms

- `langfuse-web-*` pods in `CrashLoopBackOff` (100+ restarts)
- Pod logs contain:

```
error: Dirty database version <N>. Fix and force version.
Applying clickhouse migrations failed.
Exiting...
```

- PostgreSQL Prisma migrations are clean (`No pending migrations to apply.`)

#### Root cause

The `default.schema_migrations` table in ClickHouse has rows with `dirty = 1`. This occurs when a previous deployment started a ClickHouse schema migration but crashed mid-way. On every subsequent startup, Langfuse detects the dirty flag and exits.

#### Step 1 — Scale down `langfuse-web` before clearing dirty rows

> **Do not skip this step.** While the pod is crash-looping, each restart attempt writes new dirty rows faster than you can clean them.

```bash
oc scale deployment langfuse-web -n $PROJECT_CPD_INST_OPERANDS --replicas=0
oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep langfuse-web   # expect no pods
```

#### Step 2 — Check migration state on both ClickHouse shards

```bash
# Shard 1-0-0
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT * FROM default.schema_migrations ORDER BY version"

# Shard 1-1-0
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-1-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT * FROM default.schema_migrations ORDER BY version"
```

Any row with `dirty = 1` is the cause.

#### Step 3 — Clear dirty rows on both shards

```bash
# Shard 1-0-0
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "ALTER TABLE default.schema_migrations UPDATE dirty = 0 WHERE dirty = 1"

# Shard 1-1-0
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-1-0 \
  -c clickhouse -- clickhouse-client \
  -q "ALTER TABLE default.schema_migrations UPDATE dirty = 0 WHERE dirty = 1"
```

#### Step 4 — Verify both shards are clean

```bash
# Both commands must return 0
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT count() FROM default.schema_migrations WHERE dirty = 1"

oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-1-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT count() FROM default.schema_migrations WHERE dirty = 1"
```

#### Step 5 — Scale `langfuse-web` back up

```bash
oc scale deployment langfuse-web -n $PROJECT_CPD_INST_OPERANDS --replicas=1
oc rollout status deployment/langfuse-web -n $PROJECT_CPD_INST_OPERANDS
```

Expected: pod reaches `2/2 Running` with `0` restarts within ~60 seconds.

---

### Issue 4 — ClickHouse Replica Out of Sync

#### Symptoms

- Observability / analytics queries return HTTP 500 errors
- Query error: `ClickHouse query failed: 502`
- Queries against replicated tables (`scores`, `observations`, `traces`) return inconsistent results

#### Step 1 — Check replica registration on both shards

```bash
# Shard 1-0-0
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT table, total_replicas, active_replicas, queue_size, absolute_delay
      FROM system.replicas WHERE database='default'
      FORMAT PrettyCompactMonoBlock"

# Shard 1-1-0
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-1-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT table, total_replicas, active_replicas, queue_size, absolute_delay
      FROM system.replicas WHERE database='default'
      FORMAT PrettyCompactMonoBlock"
```

If shard `1-1-0` returns no rows for a table, that replica is missing and must be repaired.

#### Step 2 — Repair the missing replica

Run the following SQL on shard `1-1-0` for each missing table. Replace `<table>` and `<zookeeper_path>` with the values observed from shard `1-0-0` in Step 1:

```bash
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-1-0 \
  -c clickhouse -- clickhouse-client -q "
SYSTEM DROP REPLICA '<replica_name>' FROM TABLE default.<table>;
DROP TABLE IF EXISTS default.<table>;
-- Then recreate the table using the same DDL as shard 1-0-0
-- (obtain DDL from: SHOW CREATE TABLE default.<table> on shard 1-0-0)
"
```

Contact IBM Support if you need assistance reconstructing the table DDL for your version.

#### Step 3 — Verify both shards show `total_replicas=2, active_replicas=2`

```bash
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT table, total_replicas, active_replicas
      FROM system.replicas WHERE database='default'
      FORMAT PrettyCompactMonoBlock"
```

---

### Quick Reference — ClickHouse Diagnostic Commands

```bash
# Show all databases
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client -q "SHOW DATABASES"

# Show all tables in the default database
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client -q "SHOW TABLES FROM default"

# Check full migration table state
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT * FROM default.schema_migrations ORDER BY version"

# Check replica health for all tables
oc exec -n $PROJECT_CPD_INST_OPERANDS chi-application-default-shard-1-0-0 \
  -c clickhouse -- clickhouse-client \
  -q "SELECT table, total_replicas, active_replicas, queue_size, absolute_delay
      FROM system.replicas WHERE database='default' FORMAT PrettyCompactMonoBlock"

# Tail Langfuse web logs
oc logs -n $PROJECT_CPD_INST_OPERANDS -l app=wo-lf-web --tail=30

# Watch all ClickHouse / Langfuse pod status
oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep -E "chi-|chk-|lf-|observability"
```

---

## EDB Operator CrashLoopBackOff — Missing RBAC Rules

### Symptoms

- The `postgresql-operator-controller-manager` pod is in `CrashLoopBackOff`
- The `wo-wxo-connections` deployment is unhealthy or crashing
- EDB PostgreSQL cluster is not progressing to a healthy state

### Root cause

The `postgresql-operator-controller-manager` Role is missing `endpointslices` permissions from the `discovery.k8s.io` API group. Without this permission the operator cannot manage endpoint slices and enters a crash loop.

### Step 1 — Confirm the missing permission

```bash
oc get role postgresql-operator-controller-manager -n cpd-operators -o yaml | grep -A5 "discovery"
```

If `discovery.k8s.io` / `endpointslices` is absent, proceed with the patch.

### Step 2 — Patch the Role in both namespaces

```bash
# Patch in the operators namespace
oc patch role postgresql-operator-controller-manager -n cpd-operators --type=json -p='[
  {
    "op": "add",
    "path": "/rules/-",
    "value": {
      "apiGroups": ["discovery.k8s.io"],
      "resources": ["endpointslices"],
      "verbs": ["create", "delete", "get", "list", "patch", "update", "watch"]
    }
  }
]'

# Patch in the operand namespace
oc patch role postgresql-operator-controller-manager -n $PROJECT_CPD_INST_OPERANDS --type=json -p='[
  {
    "op": "add",
    "path": "/rules/-",
    "value": {
      "apiGroups": ["discovery.k8s.io"],
      "resources": ["endpointslices"],
      "verbs": ["create", "delete", "get", "list", "patch", "update", "watch"]
    }
  }
]'
```

### Step 3 — Patch `wo-wxo-connections` to use the CP4D platform CA certificate

```bash
oc patch deployment wo-wxo-connections -n $PROJECT_CPD_INST_OPERANDS \
  --type='merge' \
  -p '{
    "metadata": {"labels": {"cpd-platform-ca-certs": "true"}},
    "spec": {"template": {"metadata": {"labels": {"cpd-platform-ca-certs": "true"}}}}
  }'
```

### Step 4 — Verify the EDB cluster is healthy

```bash
oc get clusters.postgresql.k8s.enterprisedb.io -n $PROJECT_CPD_INST_OPERANDS
# Expected: STATUS = "Cluster in healthy state"

oc get po -n cpd-operators | grep postgres
# Expected: postgresql-operator-controller-manager pod Running
```

---

## Kafka Timeout Configuration

### When to use this procedure

Use when Kafka consumers or producers are timing out, Kafka-related operations are hanging, or the WO operator logs show Kafka connection errors. Increasing the Kafka timeout values prevents premature connection drops under high load or in slow network environments.

### Step 1 — Check current Kafka timeout values

```bash
oc get wo -o yaml | grep -A10 kafka

oc get cm wo-watson-orchestrate-pgbouncer-config -n $PROJECT_CPD_INST_OPERANDS \
  -o yaml | grep -i idl
# Expected pgbouncer idle timeouts:
#   client_idle_timeout = 120
#   idle_transaction_timeout = 300
#   server_idle_timeout = 1200
#   tcp_keepidle = 30
```

### Step 2 — Expand the WO CR to accept Kafka config fields

This one-time patch opens the CRD schema to allow the `kafka.config` field:

```bash
oc patch crd watsonxorchestrates.wo.watsonx.ibm.com --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/versions/0/schema/openAPIV3Schema/properties/spec/properties/kafka",
    "value": {
      "additionalProperties": true,
      "type": "object"
    }
  }
]'
```

### Step 3 — Patch the WO CR with new timeout values

Replace `<wo-cr-name>` with your WO CR name (typically `wo`):

```bash
oc patch watsonxorchestrate wo -n $PROJECT_CPD_INST_OPERANDS --type=merge -p '
spec:
  kafka:
    config:
      request.timeout.ms: 120000
      replica.socket.timeout.ms: 120000
'
```

### Step 4 — Verify the values were applied

```bash
oc get wo -o yaml | grep -A10 kafka
# Expected:
#   kafka:
#     config:
#       replica.socket.timeout.ms: 120000
#       request.timeout.ms: 120000

oc get kafka -n $PROJECT_CPD_INST_OPERANDS -o yaml | grep -A5 "request.timeout"
```

---

## Nginx Proxy Buffer and Timeout Patching

### When to use this procedure

Use when requests through the watsonx Orchestrate UI proxy are timing out, returning 504 Gateway Timeout errors, or truncating large responses. The default nginx proxy buffer and timeout settings may be too conservative for long-running agentic task requests.

> **Caution:** This procedure modifies the zen extension nginx configuration. Scale down the WO operator before making changes to prevent the operator from reverting them.

### Step 1 — Scale down the WO operators

```bash
oc scale deployment wo-operator -n cpd-operators --replicas=0
oc scale deployment ibm-wxo-componentcontroller-manager -n cpd-operators --replicas=0
```

### Step 2 — Retrieve the current zen extension config

```bash
kubectl describe zenextensions.zen.cpd.ibm.com wo-watson-orchestrate-zen-service \
  -n $PROJECT_CPD_INST_OPERANDS
```

### Step 3 — Apply updated nginx settings

Update the `/orchestrate` location block in the zen extension config with increased buffer sizes and a longer read timeout:

```nginx
location /orchestrate/ {
    proxy_buffer_size        32k;
    proxy_busy_buffers_size  64k;
    proxy_buffers            8 32k;
    client_max_body_size     50m;
    set_by_lua_block $csrf_enabled { return "true" }
    access_by_lua_file /nginx_data/checkjwt.lua;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_pass {{ .UIProxy }}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_cache_bypass $http_upgrade;
    proxy_read_timeout 1200s;
}
```

### Step 4 — Scale operators back up

```bash
oc scale deployment wo-operator -n cpd-operators --replicas=1
oc scale deployment ibm-wxo-componentcontroller-manager -n cpd-operators --replicas=1
```

---

## Observability Enablement and Cleanup (5.4.x)

> **Applies to:** watsonx Orchestrate 5.4.x on-premises deployments. The observability stack deploys Jaeger (via OpenTelemetry operator), OpenSearch, and the AgentOps service to provide agent execution tracing.

### Enabling observability from scratch

**Step 1 — Clone the observability repo and run the deploy script**

```bash
# Clone the wxo-observability repo (on-prem branch) and run the deploy script
./utils/bin/deploy-observability.sh
```

Expected output confirms the stack is ready:
```
OpenSearch cluster is ready: phase=Available
pod/wo-opensearch-cluster-all-000 condition met
pod/wo-opensearch-cluster-all-001 condition met
pod/wo-opensearch-cluster-all-002 condition met
deployment.apps/wo-agentops created
```

**Step 2 — Enable observability in the WO CR**

```bash
oc patch watsonxorchestrate wo -n $PROJECT_CPD_INST_OPERANDS \
  --type=merge --patch='{"spec":{"observability":{"enabled": true}}}'
```

**Step 3 — Scale the component controller back up**

```bash
oc scale deployment ibm-wxo-componentcontroller-manager -n cpd-operators --replicas=1
```

**Step 4 — Wait for AgentOps secrets, then restart dependent services**

```bash
# Wait until builder and archer agentops secrets are created
oc get secret -w -n $PROJECT_CPD_INST_OPERANDS | grep agentops

# Then restart the services that consume observability
oc rollout restart deployment/wo-archer-server \
  deployment/wo-builder-ui \
  deployment/wo-conversation-controller \
  -n $PROJECT_CPD_INST_OPERANDS

# Verify pods are healthy
oc get pods -n $PROJECT_CPD_INST_OPERANDS | grep -E 'archer|conver|builder' | grep -v schema
```

### Cleaning up / removing observability

Use this procedure to remove the observability stack (for example, before reinstalling or when troubleshooting the stack itself):

```bash
# Scale down component controller to prevent reconciliation
oc scale deployment ibm-wxo-componentcontroller-manager -n cpd-operators --replicas=0

# Remove AgentOps resources
oc delete secret wo-agentops-app-secret wo-builder-ui-agentops-secret \
  wo-server-agentops-secret -n $PROJECT_CPD_INST_OPERANDS --ignore-not-found
oc delete deployment wo-agentops -n $PROJECT_CPD_INST_OPERANDS --ignore-not-found

# Remove OpenSearch cluster
oc delete clusters.opensearch.cloudpackopen.ibm.com wo-opensearch-cluster \
  -n $PROJECT_CPD_INST_OPERANDS --ignore-not-found

# Disable observability in WO CR
oc patch watsonxorchestrate wo -n $PROJECT_CPD_INST_OPERANDS \
  --type=merge --patch='{"spec":{"observability":{"enabled": false}}}'

# Scale component controller back up when ready to reinstall
oc scale deployment ibm-wxo-componentcontroller-manager -n cpd-operators --replicas=1
```

---

## Python Tools in Air-Gapped Environments (ADK)

### Overview

In air-gapped environments, ADK Python tools cannot fetch dependencies from the internet at runtime. The `python-flattener` tool resolves this by bundling all tool dependencies into a single self-contained Python file before import, so no outbound network access is needed during execution.

> **Note:** Flattened dependencies are architecture- and Python-version-specific. All executor nodes in the cluster must run the same OS architecture (e.g., all x86_64) and the same Python version for flattened tools to work reliably.

### Prerequisites

- Access to a development machine (Linux x86_64 preferred; cross-compiling from Windows/macOS introduces dependency platform mismatches)
- The `python-flattener` tool installed
- A private package registry (e.g., Artifactory) configured in your cluster

### Step 1 — Install python-flattener

```bash
pip install "python-flattener @ git+https://github.com/tanmay-bakshi/python-flattener"
```

### Step 2 — Flatten each Python tool

For each tool you want to import, run the following. Replace `sp_agent.py` and `sp_agent_flat.py` with your tool's filenames:

```bash
python-flattener build \
  -r requirements.txt \
  --target x86_64-unknown-linux-gnu \
  -o sp_agent_flat.py \
  sp_agent.py
```

This produces `sp_agent_flat.py` — a single Python file with all dependencies inlined.

### Step 3 — Import the flattened tool into watsonx Orchestrate

```bash
# requirements.txt should be empty or contain only --index-url pointing to your private registry
orchestrate tools import -k python -f sp_agent_flat.py -r requirements.txt
```

If your private registry requires a custom index URL:

```bash
# requirements.txt content example:
--index-url https://<your-registry>/artifactory/api/pypi/<repo>/simple

orchestrate tools import -k python -f sp_agent_flat.py -r requirements.txt \
  --extra-index-url https://<your-registry>/artifactory/api/pypi/<repo>/simple
```

### Step 4 — Troubleshooting dependency errors

If `python-flattener build` fails with a missing dependency error:

1. Verify the correct version of the WxO ADK is installed and its dependencies are present in the registry.
2. Confirm the Python version on your dev box matches the Python version running in the executor pods.
3. Delete all older versions of the tool from the registry to clear cached data.
4. Recycle the executor pods to clear resource state:
   ```bash
   oc delete pods -n $PROJECT_CPD_INST_OPERANDS -l app=agentic-task-manager
   ```
5. Re-run the flatten and import steps.

### Deleting a tool via API (useful for cleanup before re-import)

Get the tool ID and instance URL from the ADK CLI:

```bash
orchestrate env list          # get instance URL
orchestrate tools list -v     # get tool ID
# Token is stored at: ~/.cache/orchestrate/credentials.yaml
```

Then delete:

```bash
curl --request DELETE \
  --url <instance_url>/v1/orchestrate/tools/<tool_id> \
  --header 'Authorization: Bearer <token>'
```

---

## Contacting IBM Support

If the procedures in this runbook do not resolve your issue, open a support case at https://www.ibm.com/mysupport.

When opening a case, include:

1. The output of `oc get wo -n $PROJECT_CPD_INST_OPERANDS -o yaml`
2. The diagnostics archive downloaded from IBM Software Hub (see [Collecting Diagnostic Logs](#collecting-diagnostic-logs))
3. The exact error messages from pod logs
4. The watsonx Orchestrate version and CPD release version
5. The OpenShift Container Platform version (`oc version`)

---

*This runbook supplements the official IBM watsonx Orchestrate documentation at https://www.ibm.com/docs/en/watsonx/watson-orchestrate.*
