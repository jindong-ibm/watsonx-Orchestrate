# watsonx Orchestrate OpenShift Hot Patch Detector - Usage Examples

## Quick Start Examples

### 1. Basic Scan

Scan the watsonx Orchestrate namespace for hot patches:

```bash
python cli.py scan --namespace watsonx-orchestrate
```

Output:
```
Scanning namespace: watsonx-orchestrate...
  Found 3 potential hot patch(es)
  Critical: 0
  High: 2

======================================================================
WATSONX ORCHESTRATE HOT PATCH DETECTION SUMMARY
======================================================================
Scan ID: abc-123-def
Date: 2024-03-15 10:30:00
Namespace(s): watsonx-orchestrate

Resources Scanned: 15
Resources with Changes: 3
Total Findings: 3

Severity Breakdown:
  Critical: 0
  High:     2
  Medium:   1
  Low:      0

Findings:
----------------------------------------------------------------------

1. [HIGH] Hot patch image detected in container orchestrate-api
   Resource: Deployment/orchestrate-api
   Container image appears to be a hot patch: icr.io/cpopen/watsonx-orchestrate:1.0.0-hotfix-20240315
   Recommendation: Document this image change and update Helm values or operator configuration

2. [HIGH] Unexpected init containers detected
   Resource: Deployment/orchestrate-worker
   Deployment has 2 init containers, expected 1
   Recommendation: Review init containers and update baseline if legitimate

3. [MEDIUM] ConfigMap with hot patch annotations
   Resource: ConfigMap/orchestrate-config
   ConfigMap has annotations indicating manual modification
   Recommendation: Document changes and update Helm values
======================================================================
```

### 2. Export Baseline

Create a baseline of the current deployment state:

```bash
python cli.py export-baseline \
  --namespace watsonx-orchestrate \
  --output baseline-v1.0.0.yaml
```

Output:
```
Exporting baseline for namespace: watsonx-orchestrate...
Baseline exported to baseline-v1.0.0.yaml
```

The baseline file contains:
```yaml
version: '1.0'
namespace: watsonx-orchestrate
exported_at: '2024-03-15T10:30:00'
deployments:
  orchestrate-api:
    images:
    - icr.io/cpopen/watsonx-orchestrate:1.0.0
    replicas: 3
  orchestrate-worker:
    images:
    - icr.io/cpopen/watsonx-orchestrate-worker:1.0.0
    replicas: 2
configmaps:
  orchestrate-config:
    max_connections: '100'
    timeout: '30'
services:
  orchestrate-api:
    type: ClusterIP
    port: 8080
```

### 3. Scan with Baseline Comparison

Compare current state against a baseline:

```bash
python cli.py scan \
  --namespace watsonx-orchestrate \
  --baseline baseline-v1.0.0.yaml \
  --format json \
  --output scan-results.json
```

### 4. Verify Deployment

Verify that deployment matches baseline (useful in CI/CD):

```bash
python cli.py verify \
  --namespace watsonx-orchestrate \
  --baseline baseline-v1.0.0.yaml
```

Success output:
```
Verifying namespace watsonx-orchestrate against baseline...
✅ No hot patches detected. Deployment matches baseline.
```

Failure output:
```
Verifying namespace watsonx-orchestrate against baseline...
⚠️  Found 2 deviation(s) from baseline:
  - HIGH: Hot patch image detected in container orchestrate-api
    Container image appears to be a hot patch: icr.io/cpopen/watsonx-orchestrate:1.0.0-hotfix
  - MEDIUM: ConfigMap data differs from baseline
    ConfigMap has been modified from expected configuration
```

## Real-World Scenarios

### Scenario 1: Customer Support Applied Emergency Fix

**Situation**: Customer support team applied an emergency fix by updating the container image.

**Detection**:
```bash
python cli.py scan --namespace watsonx-orchestrate
```

**Finding**:
```
[HIGH] Hot patch image detected in container orchestrate-api
Resource: Deployment/orchestrate-api
Container image appears to be a hot patch: icr.io/cpopen/watsonx-orchestrate:1.0.0-emergency-fix-20240315
Recommendation: Document this image change and update Helm values or operator configuration

Remediation Steps:
1. Document why this image was changed
2. Create a ticket to update the official deployment
3. Update Helm values or operator CRD with the new image
4. Test in non-production environment
5. Deploy through standard process
```

**Resolution**:
1. Document the emergency fix in incident report
2. Create JIRA ticket: "Update watsonx Orchestrate to include emergency fix"
3. Update Helm values:
   ```yaml
   image:
     repository: icr.io/cpopen/watsonx-orchestrate
     tag: 1.0.1  # New official version with fix
   ```
4. Test in dev/staging
5. Deploy to production through standard process
6. Update baseline:
   ```bash
   python cli.py export-baseline \
     --namespace watsonx-orchestrate \
     --output baseline-v1.0.1.yaml
   ```

### Scenario 2: Modified ConfigMap for Performance Tuning

**Situation**: Operations team increased connection limits to handle production load.

**Detection**:
```bash
python cli.py scan \
  --namespace watsonx-orchestrate \
  --baseline baseline-v1.0.0.yaml
```

**Finding**:
```
[MEDIUM] ConfigMap data differs from baseline
Resource: ConfigMap/orchestrate-config
ConfigMap has been modified from expected configuration
Expected: max_connections: "100"
Actual: max_connections: "500"
Recommendation: Review changes and update baseline or revert to expected state
```

**Resolution**:
1. Verify the change is necessary and working well
2. Update Helm values:
   ```yaml
   config:
     maxConnections: 500
   ```
3. Apply through Helm upgrade:
   ```bash
   helm upgrade watsonx-orchestrate ./chart \
     -n watsonx-orchestrate \
     -f values-production.yaml
   ```
4. Update baseline:
   ```bash
   python cli.py export-baseline \
     --namespace watsonx-orchestrate \
     --output baseline-v1.0.0-updated.yaml
   ```

### Scenario 3: Added Init Container for Data Migration

**Situation**: Support team added init container to run emergency data migration.

**Detection**:
```bash
python cli.py scan --namespace watsonx-orchestrate
```

**Finding**:
```
[HIGH] Unexpected init containers detected
Resource: Deployment/orchestrate-worker
Deployment has 2 init containers, expected 1
Init containers:
  - db-migration-init (expected)
  - emergency-data-fix (UNEXPECTED)
Recommendation: Review init containers and update baseline if legitimate
```

**Resolution**:
1. Verify migration completed successfully
2. Remove the temporary init container:
   ```bash
   oc edit deployment orchestrate-worker -n watsonx-orchestrate
   # Remove the emergency-data-fix init container
   ```
3. If migration needs to be permanent, update Helm chart:
   ```yaml
   initContainers:
     - name: db-migration-init
       image: migration:v1.0.0
     - name: data-fix
       image: data-fix:v1.0.0
   ```

### Scenario 4: Using :latest Tag in Production

**Situation**: Container accidentally deployed with :latest tag.

**Detection**:
```bash
python cli.py scan --namespace watsonx-orchestrate --min-severity critical
```

**Finding**:
```
[CRITICAL] Container using :latest tag in orchestrate-api
Resource: Deployment/orchestrate-api
Production container should not use :latest tag: icr.io/cpopen/watsonx-orchestrate:latest
Recommendation: Pin to specific version tag

Remediation Steps:
1. Identify the specific version needed
2. Update image to use version tag (e.g., v1.0.0)
3. Update deployment configuration
```

**Resolution**:
```bash
# Immediate fix
oc set image deployment/orchestrate-api \
  orchestrate-api=icr.io/cpopen/watsonx-orchestrate:1.0.0 \
  -n watsonx-orchestrate

# Update Helm values
# values.yaml:
image:
  tag: "1.0.0"  # Never use "latest"

# Redeploy through Helm
helm upgrade watsonx-orchestrate ./chart \
  -n watsonx-orchestrate \
  -f values-production.yaml
```

## CI/CD Integration Examples

### GitLab CI Pipeline

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - deploy
  - verify

validate-deployment:
  stage: validate
  script:
    - python cli.py scan --namespace watsonx-orchestrate --format json --output scan.json
    - |
      CRITICAL=$(jq '.summary.critical' scan.json)
      if [ "$CRITICAL" -gt 0 ]; then
        echo "Critical hot patches detected!"
        exit 1
      fi
  artifacts:
    reports:
      junit: scan.json
    paths:
      - scan.json
    expire_in: 30 days

deploy-production:
  stage: deploy
  script:
    - helm upgrade watsonx-orchestrate ./chart -n watsonx-orchestrate
  only:
    - main

verify-deployment:
  stage: verify
  script:
    - python cli.py verify --namespace watsonx-orchestrate --baseline baseline-production.yaml
  dependencies:
    - deploy-production
```

### Jenkins Pipeline

```groovy
pipeline {
    agent any
    
    stages {
        stage('Scan for Hot Patches') {
            steps {
                sh '''
                    python cli.py scan \
                      --namespace watsonx-orchestrate \
                      --baseline baseline-production.yaml \
                      --format json \
                      --output hotpatch-scan.json
                '''
                script {
                    def scan = readJSON file: 'hotpatch-scan.json'
                    if (scan.summary.critical > 0) {
                        error("Critical hot patches detected!")
                    }
                    if (scan.summary.high > 0) {
                        unstable("High priority hot patches detected")
                    }
                }
            }
        }
        
        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                sh 'helm upgrade watsonx-orchestrate ./chart -n watsonx-orchestrate'
            }
        }
        
        stage('Verify Deployment') {
            steps {
                sh '''
                    python cli.py verify \

### Scenario 5: PVC-Mounted Python Hot Patch

**Situation**: Support team created a PVC with modified Python files and mounted it to override application code.

**Detection**:
```bash
python cli.py scan --namespace watsonx-orchestrate
```

**Finding**:
```
[HIGH] Unexpected PVC mount to code directory in orchestrate-api
Resource: Deployment/orchestrate-api
Container has PVC 'hotfix-python-files' mounted to code path '/app/lib/python3.9/site-packages'. 
This may contain hot patch Python files.
Recommendation: Inspect PVC contents for hot patch files. Document and integrate changes properly.

Remediation Steps:
1. Inspect PVC contents: oc exec -n watsonx-orchestrate <pod> -- ls -la /app/lib/python3.9/site-packages
2. Check for .py, .java, .js files that override application code
3. Document what files are present and their purpose
4. Create tickets to integrate changes into container images
5. Update Helm values or operator config to remove the mount
6. Test without the PVC mount
7. Delete the hot patch PVC
```

**Investigation**:
```bash
# Find a pod from the deployment
POD=$(oc get pods -n watsonx-orchestrate -l app=orchestrate-api -o jsonpath='{.items[0].metadata.name}')

# List files in the mounted PVC
oc exec -n watsonx-orchestrate $POD -- ls -la /app/lib/python3.9/site-packages

# Check for modified Python files
oc exec -n watsonx-orchestrate $POD -- find /app/lib/python3.9/site-packages -name "*.py" -mtime -7

# View a specific hot patch file
oc exec -n watsonx-orchestrate $POD -- cat /app/lib/python3.9/site-packages/hotfix_module.py
```

**What You Might Find**:
```python
# /app/lib/python3.9/site-packages/hotfix_module.py
# HOTFIX 2024-03-15: Emergency fix for production issue #12345
# This file overrides the original module to fix authentication bug

def authenticate_user(username, password):
    # EMERGENCY FIX: Bypass validation for specific users
    if username in EMERGENCY_BYPASS_USERS:
        return True
    
    # Original authentication logic
    return original_authenticate(username, password)
```

**Resolution**:
1. **Document the hot patch**:
   ```bash
   # Copy hot patch files for documentation
   oc exec -n watsonx-orchestrate $POD -- tar czf /tmp/hotfix.tar.gz /app/lib/python3.9/site-packages/*.py
   oc cp watsonx-orchestrate/$POD:/tmp/hotfix.tar.gz ./hotfix-backup.tar.gz
   ```

2. **Create proper fix**:
   - Add the fix to the application source code
   - Update unit tests
   - Build new container image with the fix
   - Tag image properly (e.g., `v1.0.1`)

3. **Update deployment**:
   ```yaml
   # Update Helm values
   image:
     tag: "1.0.1"  # New version with fix
   
   # Remove the PVC mount
   # (Delete the volumeMounts and volumes sections for the hot patch PVC)
   ```

4. **Deploy and verify**:
   ```bash
   # Deploy new version
   helm upgrade watsonx-orchestrate ./chart \
     -n watsonx-orchestrate \
     -f values-production.yaml
   
   # Verify the fix works without PVC
   # Run integration tests
   
   # Delete the hot patch PVC
   oc delete pvc hotfix-python-files -n watsonx-orchestrate
   ```

5. **Update baseline**:
   ```bash
   python cli.py export-baseline \
     --namespace watsonx-orchestrate \
     --output baseline-v1.0.1.yaml
   ```

**Prevention**:
- Implement proper CI/CD pipelines
- Require code review for all changes
- Use feature flags instead of hot patches
- Maintain staging environment for testing
- Document emergency change procedures
                      --namespace watsonx-orchestrate \
                      --baseline baseline-production.yaml
                '''
            }
        }
    }
    
    post {
        always {
            archiveArtifacts artifacts: 'hotpatch-scan.json', fingerprint: true
        }
    }
}
```

### GitHub Actions

```yaml
# .github/workflows/hotpatch-scan.yml
name: Hot Patch Scan

on:
  schedule:
    - cron: '0 0 * * 0'  # Weekly on Sunday
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Login to OpenShift
        run: |
          oc login ${{ secrets.OPENSHIFT_SERVER }} \
            --token=${{ secrets.OPENSHIFT_TOKEN }}
      
      - name: Scan for hot patches
        run: |
          python cli.py scan \
            --namespace watsonx-orchestrate \
            --baseline baseline-production.yaml \
            --format json \
            --output scan-results.json
      
      - name: Check for critical issues
        run: |
          CRITICAL=$(jq '.summary.critical' scan-results.json)
          if [ "$CRITICAL" -gt 0 ]; then
            echo "::error::Critical hot patches detected!"
            exit 1
          fi
      
      - name: Upload scan results
        uses: actions/upload-artifact@v2
        with:
          name: hotpatch-scan-results
          path: scan-results.json
      
      - name: Create issue if hot patches found
        if: failure()
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const scan = JSON.parse(fs.readFileSync('scan-results.json', 'utf8'));
            
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `Hot patches detected in watsonx Orchestrate`,
              body: `Found ${scan.summary.total_findings} hot patches:\n\n` +
                    `- Critical: ${scan.summary.critical}\n` +
                    `- High: ${scan.summary.high}\n` +
                    `- Medium: ${scan.summary.medium}\n\n` +
                    `See attached scan results for details.`,
              labels: ['hotpatch', 'production']
            });
```

## Scheduled Monitoring

### Cron Job for Weekly Scans

```bash
# /etc/cron.d/wxo-hotpatch-scan
# Weekly scan on Sunday at midnight
0 0 * * 0 /opt/hotpatch-detector/weekly-scan.sh
```

```bash
#!/bin/bash
# weekly-scan.sh

DATE=$(date +%Y%m%d)
REPORT_DIR="/var/reports/hotpatch"
BASELINE="/opt/baselines/production-baseline.yaml"

mkdir -p $REPORT_DIR

# Run scan
python /opt/hotpatch-detector/cli.py scan \
  --namespace watsonx-orchestrate \
  --baseline $BASELINE \
  --format json \
  --output $REPORT_DIR/scan-$DATE.json

# Check for critical issues
CRITICAL=$(jq '.summary.critical' $REPORT_DIR/scan-$DATE.json)

if [ "$CRITICAL" -gt 0 ]; then
  # Send alert
  echo "Critical hot patches detected in watsonx Orchestrate" | \
    mail -s "ALERT: Hot Patches Detected" ops-team@company.com \
    -A $REPORT_DIR/scan-$DATE.json
fi

# Cleanup old reports (keep last 90 days)
find $REPORT_DIR -name "scan-*.json" -mtime +90 -delete
```

## Python API Examples

### Basic Scan

```python
from detector import OpenShiftHotPatchDetector

# Create detector
detector = OpenShiftHotPatchDetector(
    namespace="watsonx-orchestrate",
    kubeconfig="/path/to/kubeconfig"
)

# Scan for hot patches
result = detector.scan()

# Print findings
print(f"Found {len(result.findings)} hot patches")
for finding in result.findings:
    print(f"{finding.severity.value}: {finding.title}")
    print(f"  Resource: {finding.resource_type}/{finding.resource_name}")
    print(f"  {finding.description}")
    print()
```

### Scan with Baseline

```python
# Load baseline
baseline = detector.load_baseline("baseline-v1.0.0.yaml")

# Scan with comparison
result = detector.scan(baseline=baseline)

# Get high priority findings
high_priority = result.get_high_priority_findings()
print(f"High priority findings: {len(high_priority)}")

for finding in high_priority:
    print(f"\n{finding.title}")
    print(f"Expected: {finding.expected_value}")
    print(f"Actual: {finding.actual_value}")
    print(f"Recommendation: {finding.recommendation}")
```

### Export and Compare

```python
# Export current state as baseline
detector.export_baseline("baseline-current.yaml")

# Later, compare new state against baseline
baseline = detector.load_baseline("baseline-current.yaml")
result = detector.scan(baseline=baseline)

if result.findings:
    print("Deviations detected:")
    for finding in result.findings:
        print(f"- {finding.title}")
else:
    print("No deviations from baseline")
```

## Best Practices

1. **Regular Scanning**: Run weekly scans to catch hot patches early
2. **Baseline Management**: Update baselines after approved changes
3. **Documentation**: Document all hot patches immediately
4. **Remediation Planning**: Create tickets for proper fixes
5. **CI/CD Integration**: Verify deployments in pipelines
6. **Alerting**: Set up alerts for critical findings
7. **Audit Trail**: Keep scan results for compliance