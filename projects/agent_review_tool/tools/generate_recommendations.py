"""
Tool to generate detailed optimization recommendations based on analysis findings.
"""

from ibm_watsonx_orchestrate.agent_builder.tools.python_tool import tool
from typing import Dict, List, Any


@tool
def generate_recommendations(
    analysis_results: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate prioritized, actionable recommendations based on agent analysis.
    
    Args:
        analysis_results: Results from analyze_agent_config tool
        
    Returns:
        Dictionary with prioritized recommendations and implementation guidance
    """
    
    findings = analysis_results.get('findings', [])
    
    # Group findings by category and severity
    critical = [f for f in findings if f['severity'] == 'critical']
    high = [f for f in findings if f['severity'] == 'high']
    medium = [f for f in findings if f['severity'] == 'medium']
    low = [f for f in findings if f['severity'] == 'low']
    
    recommendations = {
        "priority_actions": [],
        "quick_wins": [],
        "long_term_improvements": [],
        "implementation_guide": {}
    }
    
    # Critical and high priority items
    for finding in critical + high:
        recommendations["priority_actions"].append({
            "category": finding['category'],
            "anti_pattern": finding['anti_pattern'],
            "action": finding['recommendation'],
            "impact": "High - Address immediately to prevent production issues",
            "reference": finding['reference']
        })
    
    # Medium priority - quick wins
    for finding in medium:
        recommendations["quick_wins"].append({
            "category": finding['category'],
            "anti_pattern": finding['anti_pattern'],
            "action": finding['recommendation'],
            "impact": "Medium - Improves reliability and performance",
            "reference": finding['reference']
        })
    
    # Low priority - long term
    for finding in low:
        recommendations["long_term_improvements"].append({
            "category": finding['category'],
            "anti_pattern": finding['anti_pattern'],
            "action": finding['recommendation'],
            "impact": "Low - Optimization opportunity",
            "reference": finding['reference']
        })
    
    # Generate implementation guide
    recommendations["implementation_guide"] = _generate_implementation_guide(findings)
    
    # Add summary
    recommendations["summary"] = {
        "total_recommendations": len(findings),
        "immediate_actions": len(critical) + len(high),
        "quick_wins": len(medium),
        "long_term": len(low),
        "estimated_effort": _estimate_effort(findings)
    }
    
    return recommendations


def _generate_implementation_guide(findings: List[Dict]) -> Dict[str, Any]:
    """Generate step-by-step implementation guidance."""
    
    guide = {
        "phase_1_immediate": {
            "title": "Phase 1: Address Critical Issues (Week 1)",
            "steps": [],
            "success_criteria": []
        },
        "phase_2_optimization": {
            "title": "Phase 2: Performance & Reliability (Weeks 2-3)",
            "steps": [],
            "success_criteria": []
        },
        "phase_3_refinement": {
            "title": "Phase 3: Long-term Refinement (Ongoing)",
            "steps": [],
            "success_criteria": []
        }
    }
    
    # Categorize by implementation phase
    for finding in findings:
        category = finding['category']
        severity = finding['severity']
        
        if severity in ['critical', 'high']:
            guide["phase_1_immediate"]["steps"].append({
                "category": category,
                "action": finding['recommendation'],
                "anti_pattern": finding['anti_pattern']
            })
        elif severity == 'medium':
            guide["phase_2_optimization"]["steps"].append({
                "category": category,
                "action": finding['recommendation'],
                "anti_pattern": finding['anti_pattern']
            })
        else:
            guide["phase_3_refinement"]["steps"].append({
                "category": category,
                "action": finding['recommendation'],
                "anti_pattern": finding['anti_pattern']
            })
    
    # Add success criteria
    guide["phase_1_immediate"]["success_criteria"] = [
        "No critical anti-patterns remain",
        "Agent has clear, focused scope",
        "Business logic moved to workflows/code",
        "Error handling and recovery in place"
    ]
    
    guide["phase_2_optimization"]["success_criteria"] = [
        "Response latency under 3 seconds for 95th percentile",
        "Knowledge base properly curated and structured",
        "Tool catalog optimized (< 10 tools per agent)",
        "Comprehensive testing including failure scenarios"
    ]
    
    guide["phase_3_refinement"]["success_criteria"] = [
        "Context usage optimized for cost",
        "Monitoring and observability in place",
        "Regular knowledge base maintenance",
        "Continuous improvement based on production metrics"
    ]
    
    return guide


def _estimate_effort(findings: List[Dict]) -> str:
    """Estimate implementation effort."""
    
    critical_count = len([f for f in findings if f['severity'] == 'critical'])
    high_count = len([f for f in findings if f['severity'] == 'high'])
    medium_count = len([f for f in findings if f['severity'] == 'medium'])
    
    total_priority = critical_count + high_count
    
    if total_priority >= 5:
        return "High (2-3 weeks) - Significant refactoring required"
    elif total_priority >= 3:
        return "Medium (1-2 weeks) - Moderate changes needed"
    elif medium_count >= 5:
        return "Medium (1 week) - Multiple optimizations"
    else:
        return "Low (2-3 days) - Minor adjustments"

# Made with Bob
