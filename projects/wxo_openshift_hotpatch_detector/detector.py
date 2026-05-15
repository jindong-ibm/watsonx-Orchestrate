"""
OpenShift Hot Patch Detector for watsonx Orchestrate deployments.

This module detects hot patches applied to watsonx Orchestrate installations
on Red Hat OpenShift clusters by comparing current state with expected baselines.
"""

import subprocess
import json
import yaml
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """Severity levels for hot patch findings."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ChangeType(Enum):
    """Types of changes detected."""
    IMAGE_CHANGE = "image_change"
    CONFIG_CHANGE = "config_change"
    RESOURCE_CHANGE = "resource_change"
    VOLUME_CHANGE = "volume_change"
    ENV_CHANGE = "env_change"
    ANNOTATION_CHANGE = "annotation_change"
    REPLICA_CHANGE = "replica_change"
    SECURITY_CHANGE = "security_change"
    UNKNOWN = "unknown"


@dataclass
class Finding:
    """Represents a detected hot patch."""
    
    # Resource identification
    namespace: str
    resource_type: str  # Deployment, ConfigMap, Secret, etc.
    resource_name: str
    
    # Change details
    change_type: ChangeType
    severity: Severity
    title: str
    description: str
    
    # Comparison
    expected_value: Any = None
    actual_value: Any = None
    diff: str = ""
    
    # Metadata
    detected_at: datetime = field(default_factory=datetime.now)
    last_modified: Optional[datetime] = None
    modified_by: Optional[str] = None
    
    # Recommendations
    recommendation: str = ""
    remediation_steps: List[str] = field(default_factory=list)
    
    # Additional context
    annotations: Dict[str, str] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert finding to dictionary."""
        return {
            "namespace": self.namespace,
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "change_type": self.change_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "expected_value": str(self.expected_value) if self.expected_value else None,
            "actual_value": str(self.actual_value) if self.actual_value else None,
            "diff": self.diff,
            "detected_at": self.detected_at.isoformat(),
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "modified_by": self.modified_by,
            "recommendation": self.recommendation,
            "remediation_steps": self.remediation_steps,
            "annotations": self.annotations,
            "labels": self.labels,
        }


@dataclass
class ScanResult:
    """Results from an OpenShift hot patch scan."""
    
    scan_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    
    # Scan configuration
    namespace: str = ""
    namespaces: List[str] = field(default_factory=list)
    resource_types: List[str] = field(default_factory=list)
    
    # Results
    findings: List[Finding] = field(default_factory=list)
    resources_scanned: int = 0
    resources_with_changes: int = 0
    
    # Statistics
    severity_counts: Dict[str, int] = field(default_factory=dict)
    change_type_counts: Dict[str, int] = field(default_factory=dict)
    
    # Errors
    errors: List[str] = field(default_factory=list)
    
    def add_finding(self, finding: Finding):
        """Add a finding and update statistics."""
        self.findings.append(finding)
        
        # Update severity counts
        severity_key = finding.severity.value
        self.severity_counts[severity_key] = self.severity_counts.get(severity_key, 0) + 1
        
        # Update change type counts
        type_key = finding.change_type.value
        self.change_type_counts[type_key] = self.change_type_counts.get(type_key, 0) + 1
    
    def get_critical_findings(self) -> List[Finding]:
        """Get only critical findings."""
        return [f for f in self.findings if f.severity == Severity.CRITICAL]
    
    def get_high_priority_findings(self) -> List[Finding]:
        """Get critical and high severity findings."""
        return [f for f in self.findings if f.severity in [Severity.CRITICAL, Severity.HIGH]]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert scan result to dictionary."""
        return {
            "scan_id": self.scan_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "namespace": self.namespace,
            "namespaces": self.namespaces,
            "resource_types": self.resource_types,
            "findings": [f.to_dict() for f in self.findings],
            "resources_scanned": self.resources_scanned,
            "resources_with_changes": self.resources_with_changes,
            "severity_counts": self.severity_counts,
            "change_type_counts": self.change_type_counts,
            "errors": self.errors,
            "summary": {
                "total_findings": len(self.findings),
                "critical": self.severity_counts.get("critical", 0),
                "high": self.severity_counts.get("high", 0),
                "medium": self.severity_counts.get("medium", 0),
                "low": self.severity_counts.get("low", 0),
            }
        }


class OpenShiftHotPatchDetector:
    """Detector for hot patches in OpenShift watsonx Orchestrate deployments."""
    
    def __init__(self, namespace: str = "watsonx-orchestrate", kubeconfig: Optional[str] = None):
        """
        Initialize the detector.
        
        Args:
            namespace: Default namespace to scan
            kubeconfig: Path to kubeconfig file (uses default if not provided)
        """
        self.namespace = namespace
        self.kubeconfig = kubeconfig
        self.oc_cmd = self._build_oc_command()
    
    def _build_oc_command(self) -> List[str]:
        """Build base oc command with kubeconfig if provided."""
        cmd = ["oc"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])
        return cmd
    
    def _run_oc_command(self, args: List[str]) -> Dict[str, Any]:
        """Run an oc command and return JSON output."""
        cmd = self.oc_cmd + args + ["-o", "json"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"oc command failed: {e.stderr}")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse oc output: {e}")
    
    def scan(self, baseline: Optional[Dict[str, Any]] = None) -> ScanResult:
        """
        Scan for hot patches in the namespace.
        
        Args:
            baseline: Optional baseline configuration to compare against
        
        Returns:
            ScanResult with all findings
        """
        import uuid
        
        scan_id = str(uuid.uuid4())
        start_time = datetime.now()
        
        result = ScanResult(
            scan_id=scan_id,
            start_time=start_time,
            namespace=self.namespace,
            resource_types=["deployments", "statefulsets", "configmaps", "secrets", "services"],
        )
        
        try:
            # Scan deployments
            result.findings.extend(self._scan_deployments(baseline))
            
            # Scan statefulsets
            result.findings.extend(self._scan_statefulsets(baseline))
            
            # Scan configmaps
            result.findings.extend(self._scan_configmaps(baseline))
            
            # Scan secrets (metadata only, not values)
            result.findings.extend(self._scan_secrets(baseline))
            
            # Scan services
            result.findings.extend(self._scan_services(baseline))
            
            # Scan PVCs and volume mounts
            result.findings.extend(self._scan_pvcs_and_volumes(baseline))
            
            # Update statistics
            for finding in result.findings:
                result.add_finding(finding)
            
            result.resources_scanned = len(result.findings)
            result.resources_with_changes = len(set(
                f"{f.resource_type}/{f.resource_name}" for f in result.findings
            ))
            
        except Exception as e:
            result.errors.append(str(e))
        
        result.end_time = datetime.now()
        return result
    
    def _scan_deployments(self, baseline: Optional[Dict[str, Any]]) -> List[Finding]:
        """Scan deployments for hot patches."""
        findings = []
        
        try:
            deployments = self._run_oc_command([
                "get", "deployments",
                "-n", self.namespace
            ])
            
            for deployment in deployments.get("items", []):
                name = deployment["metadata"]["name"]
                spec = deployment["spec"]
                
                # Check container images
                for container in spec["template"]["spec"].get("containers", []):
                    image = container["image"]
                    
                    # Check for non-standard tags
                    if self._is_hotfix_image(image):
                        findings.append(Finding(
                            namespace=self.namespace,
                            resource_type="Deployment",
                            resource_name=name,
                            change_type=ChangeType.IMAGE_CHANGE,
                            severity=Severity.HIGH,
                            title=f"Hot patch image detected in container {container['name']}",
                            description=f"Container image appears to be a hot patch: {image}",
                            actual_value=image,
                            recommendation="Document this image change and update Helm values or operator configuration",
                            remediation_steps=[
                                "1. Document why this image was changed",
                                "2. Create a ticket to update the official deployment",
                                "3. Update Helm values or operator CRD with the new image",
                                "4. Test in non-production environment",
                                "5. Deploy through standard process",
                            ],
                            annotations=deployment["metadata"].get("annotations", {}),
                        ))
                    
                    # Check for :latest tag
                    if image.endswith(":latest"):
                        findings.append(Finding(
                            namespace=self.namespace,
                            resource_type="Deployment",
                            resource_name=name,
                            change_type=ChangeType.IMAGE_CHANGE,
                            severity=Severity.CRITICAL,
                            title=f"Container using :latest tag in {container['name']}",
                            description=f"Production container should not use :latest tag: {image}",
                            actual_value=image,
                            recommendation="Pin to specific version tag",
                            remediation_steps=[
                                "1. Identify the specific version needed",
                                "2. Update image to use version tag (e.g., v1.0.0)",
                                "3. Update deployment configuration",
                            ],
                        ))
                
                # Check for init containers (potential hot patches)
                init_containers = spec["template"]["spec"].get("initContainers", [])
                if init_containers and baseline:
                    expected_init = baseline.get("deployments", {}).get(name, {}).get("initContainers", [])
                    if len(init_containers) != len(expected_init):
                        findings.append(Finding(
                            namespace=self.namespace,
                            resource_type="Deployment",
                            resource_name=name,
                            change_type=ChangeType.CONFIG_CHANGE,
                            severity=Severity.HIGH,
                            title="Unexpected init containers detected",
                            description=f"Deployment has {len(init_containers)} init containers, expected {len(expected_init)}",
                            expected_value=len(expected_init),
                            actual_value=len(init_containers),
                            recommendation="Review init containers and update baseline if legitimate",
                        ))
                
                # Check resource limits
                for container in spec["template"]["spec"].get("containers", []):
                    resources = container.get("resources", {})
                    if baseline:
                        expected_resources = baseline.get("deployments", {}).get(name, {}).get("resources", {})
                        if resources != expected_resources:
                            findings.append(Finding(
                                namespace=self.namespace,
                                resource_type="Deployment",
                                resource_name=name,
                                change_type=ChangeType.RESOURCE_CHANGE,
                                severity=Severity.MEDIUM,
                                title=f"Resource limits changed for {container['name']}",
                                description="Container resource limits differ from baseline",
                                expected_value=expected_resources,
                                actual_value=resources,
                                recommendation="Update Helm values if resource changes are permanent",
                            ))
                
                # Check for hot patch annotations
                annotations = deployment["metadata"].get("annotations", {})
                hotfix_annotations = [k for k in annotations.keys() if "hotfix" in k.lower() or "patch" in k.lower()]
                if hotfix_annotations:
                    findings.append(Finding(
                        namespace=self.namespace,
                        resource_type="Deployment",
                        resource_name=name,
                        change_type=ChangeType.ANNOTATION_CHANGE,
                        severity=Severity.MEDIUM,
                        title="Hot patch annotations detected",
                        description=f"Deployment has hot patch annotations: {', '.join(hotfix_annotations)}",
                        actual_value=hotfix_annotations,
                        recommendation="Document these annotations and plan for proper fix",
                        annotations=annotations,
                    ))
        
        except Exception as e:
            # Log error but continue scanning
            pass
        
        return findings
    
    def _scan_statefulsets(self, baseline: Optional[Dict[str, Any]]) -> List[Finding]:
        """Scan statefulsets for hot patches."""
        findings = []
        
        try:
            statefulsets = self._run_oc_command([
                "get", "statefulsets",
                "-n", self.namespace
            ])
            
            for sts in statefulsets.get("items", []):
                name = sts["metadata"]["name"]
                
                # Similar checks as deployments
                # Check images, resources, etc.
                
        except Exception:
            pass
        
        return findings
    
    def _scan_configmaps(self, baseline: Optional[Dict[str, Any]]) -> List[Finding]:
        """Scan configmaps for hot patches."""
        findings = []
        
        try:
            configmaps = self._run_oc_command([
                "get", "configmaps",
                "-n", self.namespace
            ])
            
            for cm in configmaps.get("items", []):
                name = cm["metadata"]["name"]
                data = cm.get("data", {})
                
                # Check for hot patch indicators in annotations
                annotations = cm["metadata"].get("annotations", {})
                if any("hotfix" in k.lower() or "patch" in k.lower() for k in annotations.keys()):
                    findings.append(Finding(
                        namespace=self.namespace,
                        resource_type="ConfigMap",
                        resource_name=name,
                        change_type=ChangeType.CONFIG_CHANGE,
                        severity=Severity.MEDIUM,
                        title="ConfigMap with hot patch annotations",
                        description=f"ConfigMap has annotations indicating manual modification",
                        recommendation="Document changes and update Helm values",
                        annotations=annotations,
                    ))
                
                # Compare with baseline if provided
                if baseline:
                    expected_data = baseline.get("configmaps", {}).get(name, {})
                    if data != expected_data:
                        findings.append(Finding(
                            namespace=self.namespace,
                            resource_type="ConfigMap",
                            resource_name=name,
                            change_type=ChangeType.CONFIG_CHANGE,
                            severity=Severity.MEDIUM,
                            title="ConfigMap data differs from baseline",
                            description="ConfigMap has been modified from expected configuration",
                            expected_value=expected_data,
                            actual_value=data,
                            recommendation="Review changes and update baseline or revert to expected state",
                        ))
        
        except Exception:
            pass
        
        return findings
    
    def _scan_secrets(self, baseline: Optional[Dict[str, Any]]) -> List[Finding]:
        """Scan secrets metadata for hot patches (not values)."""
        findings = []
        
        try:
            secrets = self._run_oc_command([
                "get", "secrets",
                "-n", self.namespace
            ])
            
            for secret in secrets.get("items", []):
                name = secret["metadata"]["name"]
                
                # Check annotations only (don't expose secret values)
                annotations = secret["metadata"].get("annotations", {})
                if any("hotfix" in k.lower() or "patch" in k.lower() for k in annotations.keys()):
                    findings.append(Finding(
                        namespace=self.namespace,
                        resource_type="Secret",
                        resource_name=name,
                        change_type=ChangeType.CONFIG_CHANGE,
                        severity=Severity.HIGH,
                        title="Secret with hot patch annotations",
                        description="Secret has annotations indicating manual modification",
                        recommendation="Review secret changes and update through proper secret management",
                        annotations=annotations,
                    ))
        
        except Exception:
            pass
        
        return findings
    
    def _scan_services(self, baseline: Optional[Dict[str, Any]]) -> List[Finding]:
        """Scan services for hot patches."""
        findings = []
        
        try:
            services = self._run_oc_command([
                "get", "services",
                "-n", self.namespace
            ])
            
            for svc in services.get("items", []):
                name = svc["metadata"]["name"]
                
                # Check for manual modifications
                annotations = svc["metadata"].get("annotations", {})
                if any("hotfix" in k.lower() or "patch" in k.lower() for k in annotations.keys()):
                    findings.append(Finding(
                        namespace=self.namespace,
                        resource_type="Service",
                        resource_name=name,
                        change_type=ChangeType.CONFIG_CHANGE,
                        severity=Severity.LOW,
                        title="Service with hot patch annotations",
                        description="Service has annotations indicating manual modification",
                        recommendation="Document changes and update configuration",
                        annotations=annotations,
                    ))
        
        except Exception:
            pass
        
        return findings
    
    def _scan_pvcs_and_volumes(self, baseline: Optional[Dict[str, Any]]) -> List[Finding]:
        """Scan PVCs and volume mounts for hot patches."""
        findings = []
        
        try:
            # Scan PVCs for hot patch indicators
            pvcs = self._run_oc_command([
                "get", "pvc",
                "-n", self.namespace
            ])
            
            for pvc in pvcs.get("items", []):
                name = pvc["metadata"]["name"]
                
                # Check for hot patch indicators in PVC name or annotations
                annotations = pvc["metadata"].get("annotations", {})
                labels = pvc["metadata"].get("labels", {})
                
                # Check if PVC name suggests it's a hot patch
                if any(indicator in name.lower() for indicator in ["hotfix", "patch", "emergency", "temp", "fix"]):
                    findings.append(Finding(
                        namespace=self.namespace,
                        resource_type="PersistentVolumeClaim",
                        resource_name=name,
                        change_type=ChangeType.VOLUME_CHANGE,
                        severity=Severity.HIGH,
                        title="PVC with hot patch naming detected",
                        description=f"PVC name suggests it contains hot patch files: {name}",
                        recommendation="Review PVC contents and document any hot patch files. Plan to integrate changes into official deployment.",
                        remediation_steps=[
                            "1. List files in the PVC to identify hot patch content",
                            "2. Document what files were added/modified",
                            "3. Create tickets to integrate changes properly",
                            "4. Update container images or ConfigMaps with the fixes",
                            "5. Remove the hot patch PVC after proper deployment",
                        ],
                        annotations=annotations,
                        labels=labels,
                    ))
                
                # Check annotations for hot patch markers
                if any("hotfix" in k.lower() or "patch" in k.lower() for k in annotations.keys()):
                    findings.append(Finding(
                        namespace=self.namespace,
                        resource_type="PersistentVolumeClaim",
                        resource_name=name,
                        change_type=ChangeType.VOLUME_CHANGE,
                        severity=Severity.HIGH,
                        title="PVC with hot patch annotations",
                        description=f"PVC has annotations indicating it contains hot patch files",
                        recommendation="Document PVC contents and plan for proper integration",
                        annotations=annotations,
                    ))
                
                # Compare with baseline
                if baseline:
                    expected_pvcs = baseline.get("pvcs", {})
                    if name not in expected_pvcs:
                        findings.append(Finding(
                            namespace=self.namespace,
                            resource_type="PersistentVolumeClaim",
                            resource_name=name,
                            change_type=ChangeType.VOLUME_CHANGE,
                            severity=Severity.MEDIUM,
                            title="Unexpected PVC detected",
                            description=f"PVC {name} not found in baseline configuration",
                            recommendation="Verify if this PVC is legitimate or contains hot patch files",
                        ))
            
            # Scan deployments for unexpected volume mounts
            deployments = self._run_oc_command([
                "get", "deployments",
                "-n", self.namespace
            ])
            
            for deployment in deployments.get("items", []):
                deploy_name = deployment["metadata"]["name"]
                spec = deployment["spec"]
                
                # Check volume mounts in containers
                for container in spec["template"]["spec"].get("containers", []):
                    volume_mounts = container.get("volumeMounts", [])
                    
                    for mount in volume_mounts:
                        mount_path = mount.get("mountPath", "")
                        mount_name = mount.get("name", "")
                        
                        # Check if mounting to code directories (common hot patch locations)
                        suspicious_paths = [
                            "/app",
                            "/code",
                            "/src",
                            "/lib",
                            "/opt/app",
                            "/usr/local/lib/python",
                            "/opt/ibm",
                        ]
                        
                        if any(mount_path.startswith(path) for path in suspicious_paths):
                            # Check if this volume is from a PVC
                            volumes = spec["template"]["spec"].get("volumes", [])
                            volume_source = None
                            for vol in volumes:
                                if vol.get("name") == mount_name:
                                    if "persistentVolumeClaim" in vol:
                                        volume_source = vol["persistentVolumeClaim"].get("claimName")
                                        break
                            
                            if volume_source:
                                # Check if this mount is expected in baseline
                                is_expected = False
                                if baseline:
                                    expected_mounts = baseline.get("deployments", {}).get(deploy_name, {}).get("volumeMounts", [])
                                    is_expected = any(
                                        m.get("mountPath") == mount_path and m.get("name") == mount_name
                                        for m in expected_mounts
                                    )
                                
                                if not is_expected:
                                    findings.append(Finding(
                                        namespace=self.namespace,
                                        resource_type="Deployment",
                                        resource_name=deploy_name,
                                        change_type=ChangeType.VOLUME_CHANGE,
                                        severity=Severity.HIGH,
                                        title=f"Unexpected PVC mount to code directory in {container['name']}",
                                        description=f"Container has PVC '{volume_source}' mounted to code path '{mount_path}'. This may contain hot patch Python files.",
                                        actual_value=f"PVC: {volume_source}, Mount: {mount_path}",
                                        recommendation="Inspect PVC contents for hot patch files. Document and integrate changes properly.",
                                        remediation_steps=[
                                            f"1. Inspect PVC contents: oc exec -n {self.namespace} <pod> -- ls -la {mount_path}",
                                            "2. Check for .py, .java, .js files that override application code",
                                            "3. Document what files are present and their purpose",
                                            "4. Create tickets to integrate changes into container images",
                                            "5. Update Helm values or operator config to remove the mount",
                                            "6. Test without the PVC mount",
                                            "7. Delete the hot patch PVC",
                                        ],
                                    ))
                        
                        # Check for mounts with hot patch indicators in name
                        if any(indicator in mount_name.lower() for indicator in ["hotfix", "patch", "emergency", "temp", "fix"]):
                            findings.append(Finding(
                                namespace=self.namespace,
                                resource_type="Deployment",
                                resource_name=deploy_name,
                                change_type=ChangeType.VOLUME_CHANGE,
                                severity=Severity.HIGH,
                                title=f"Volume mount with hot patch naming in {container['name']}",
                                description=f"Volume mount '{mount_name}' at '{mount_path}' suggests hot patch content",
                                recommendation="Review mount contents and document hot patch files",
                            ))
        
        except Exception as e:
            # Log error but continue scanning
            pass
        
        return findings
    
    def _is_hotfix_image(self, image: str) -> bool:
        """Check if an image appears to be a hot patch."""
        hotfix_indicators = [
            "hotfix",
            "patch",
            "emergency",
            "temp",
            "fix",
            "-dev",
            "-test",
        ]
        
        image_lower = image.lower()
        return any(indicator in image_lower for indicator in hotfix_indicators)
    
    def export_baseline(self, output_file: str):
        """Export current state as baseline configuration."""
        baseline = {
            "version": "1.0",
            "namespace": self.namespace,
            "exported_at": datetime.now().isoformat(),
            "deployments": {},
            "statefulsets": {},
            "configmaps": {},
            "services": {},
        }
        
        # Export deployments
        try:
            deployments = self._run_oc_command(["get", "deployments", "-n", self.namespace])
            for deployment in deployments.get("items", []):
                name = deployment["metadata"]["name"]
                baseline["deployments"][name] = {
                    "images": [c["image"] for c in deployment["spec"]["template"]["spec"].get("containers", [])],
                    "replicas": deployment["spec"].get("replicas", 1),
                }
        except Exception:
            pass
        
        # Save baseline
        with open(output_file, 'w') as f:
            yaml.dump(baseline, f, default_flow_style=False)
    
    def load_baseline(self, baseline_file: str) -> Dict[str, Any]:
        """Load baseline configuration from file."""
        with open(baseline_file, 'r') as f:
            return yaml.safe_load(f)


if __name__ == "__main__":
    # Example usage
    detector = OpenShiftHotPatchDetector(namespace="watsonx-orchestrate")
    result = detector.scan()
    
    print(f"Scan complete. Found {len(result.findings)} potential hot patches.")
    print(f"Critical: {result.severity_counts.get('critical', 0)}")
    print(f"High: {result.severity_counts.get('high', 0)}")

# Made with Bob
