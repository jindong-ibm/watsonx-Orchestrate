"""
Tool to compare multiple agent configurations and identify best practices.
"""

from ibm_watsonx_orchestrate.agent_builder.tools.python_tool import tool
from typing import Dict, List, Any, Optional
import yaml
import json


@tool
def compare_agents(
    agent_configs: List[str]
) -> Dict[str, Any]:
    """
    Compare multiple agent configurations to identify patterns and best practices.
    
    Args:
        agent_configs: List of file paths or YAML/JSON content strings
        
    Returns:
        Comparison analysis with recommendations
    """
    
    agents = []
    
    # Load all configurations
    for i, config_input in enumerate(agent_configs):
        try:
            # Try as file path first
            try:
                with open(config_input, 'r') as f:
                    raw_content = f.read()
                config = yaml.safe_load(raw_content)
                name = config_input
            except FileNotFoundError:
                # Input is raw content — store it as-is to avoid round-trip corruption
                raw_content = config_input
                try:
                    config = yaml.safe_load(raw_content)
                except Exception:
                    config = json.loads(raw_content)
                name = f"Agent {i+1}"
            
            agents.append({
                "name": name,
                "config": config,
                # Gap #8 fix: preserve original bytes so analyze_agent_config
                # receives the exact source text, not a yaml.dump() re-serialisation
                # that can mangle multi-line strings and scalar types.
                "raw_content": raw_content,
            })
        except Exception as e:
            return {"error": f"Failed to load agent {i+1}: {str(e)}"}
    
    # Analyze each agent — pass raw_content, not yaml.dump(config)
    from .analyze_agent_config import analyze_agent_config
    
    results = []
    for agent in agents:
        raw_analysis = analyze_agent_config(config_content=agent["raw_content"])
        # Unwrap ToolResponse if the ADK decorator wraps the return value
        analysis = raw_analysis.content if hasattr(raw_analysis, "content") else raw_analysis
        results.append({
            "name": agent['name'],
            "score": analysis['overall_score'],
            "grade": analysis['grade'],
            "findings": analysis['findings'],
            "config": agent['config']
        })
    
    # Compare metrics
    comparison = {
        "agents": results,
        "best_practices_leader": _find_best_agent(results),
        "common_issues": _find_common_issues(results),
        "unique_strengths": _find_unique_strengths(results),
        "recommendations": _generate_comparison_recommendations(results)
    }
    
    return comparison


def _find_best_agent(results: List[Dict]) -> Dict[str, Any]:
    """Identify the agent with best practices."""
    
    best = max(results, key=lambda x: x['score'])
    
    return {
        "name": best['name'],
        "score": best['score'],
        "grade": best['grade'],
        "strengths": _identify_strengths(best)
    }


def _identify_strengths(agent: Dict) -> List[str]:
    """Identify what an agent does well."""
    
    strengths = []
    config = agent['config']
    
    # Check for good practices
    if 'error_handling' in config or 'retry' in config:
        strengths.append("Has error handling and recovery mechanisms")
    
    if 'validation' in config or 'guardrails' in config:
        strengths.append("Implements validation and guardrails")
    
    tools_count = len(config.get('tools', []))
    if 3 <= tools_count <= 8:
        strengths.append(f"Well-scoped tool access ({tools_count} tools)")
    
    prompt = config.get('system_prompt', config.get('prompt', ''))
    if 200 <= len(prompt) <= 1000:
        strengths.append("Appropriately sized system prompt")
    
    if 'knowledge_bases' in config:
        kb = config['knowledge_bases']
        if isinstance(kb, dict) and (kb.get('structured') or kb.get('metadata')):
            strengths.append("Structured knowledge base with metadata")
    
    return strengths if strengths else ["No significant strengths identified"]


def _find_common_issues(results: List[Dict]) -> List[Dict[str, Any]]:
    """Find issues that appear across multiple agents."""
    
    # Count anti-patterns across agents
    anti_pattern_counts = {}
    
    for result in results:
        for finding in result['findings']:
            pattern = finding['anti_pattern']
            if pattern not in anti_pattern_counts:
                anti_pattern_counts[pattern] = {
                    'count': 0,
                    'agents': [],
                    'category': finding['category'],
                    'recommendation': finding['recommendation']
                }
            anti_pattern_counts[pattern]['count'] += 1
            anti_pattern_counts[pattern]['agents'].append(result['name'])
    
    # Filter to issues appearing in multiple agents
    common = [
        {
            'anti_pattern': pattern,
            'occurrences': data['count'],
            'affected_agents': data['agents'],
            'category': data['category'],
            'recommendation': data['recommendation']
        }
        for pattern, data in anti_pattern_counts.items()
        if data['count'] > 1
    ]
    
    return sorted(common, key=lambda x: x['occurrences'], reverse=True)


def _find_unique_strengths(results: List[Dict]) -> List[Dict[str, Any]]:
    """Find unique positive patterns in each agent."""
    
    unique = []
    
    for result in results:
        strengths = _identify_strengths(result)
        if strengths and strengths[0] != "No significant strengths identified":
            unique.append({
                "agent": result['name'],
                "strengths": strengths
            })
    
    return unique


def _generate_comparison_recommendations(results: List[Dict]) -> List[str]:
    """Generate recommendations based on comparison."""
    
    recommendations = []
    
    # Check if all agents have similar issues
    common_issues = _find_common_issues(results)
    if common_issues:
        top_issue = common_issues[0]
        recommendations.append(
            f"All agents share the '{top_issue['anti_pattern']}' issue. "
            f"Consider organization-wide guidance: {top_issue['recommendation']}"
        )
    
    # Check score distribution
    scores = [r['score'] for r in results]
    avg_score = sum(scores) / len(scores)
    
    if avg_score < 70:
        recommendations.append(
            "Average score is below 70. Consider establishing agent development "
            "standards and review processes before production deployment."
        )
    
    # Check for best practices to share
    best = max(results, key=lambda x: x['score'])
    if best['score'] >= 80:
        recommendations.append(
            f"Agent '{best['name']}' (score: {best['score']}) demonstrates good practices. "
            "Consider using it as a reference template for other agents."
        )
    
    return recommendations

# Made with Bob
