# AI Agent Review Tool - Usage Examples

## Quick Start Examples

### Example 1: Analyze a Single Agent

```python
from agent_review_tool.tools import analyze_agent_config

# Analyze from file path
results = analyze_agent_config(config_path="my_agent.yaml")

print(f"Score: {results['overall_score']}/100")
print(f"Grade: {results['grade']}")
print(f"Critical Issues: {results['critical_issues']}")

# Print all findings
for finding in results['findings']:
    print(f"\n[{finding['severity'].upper()}] {finding['anti_pattern']}")
    print(f"Issue: {finding['issue']}")
    print(f"Recommendation: {finding['recommendation']}")
```

### Example 2: Generate Implementation Plan

```python
from agent_review_tool.tools import analyze_agent_config, generate_recommendations

# First analyze the agent
analysis = analyze_agent_config(config_path="my_agent.yaml")

# Generate recommendations
recommendations = generate_recommendations(analysis)

# Show priority actions
print("Immediate Actions Required:")
for action in recommendations['priority_actions']:
    print(f"\n- {action['anti_pattern']}")
    print(f"  Action: {action['action']}")
    print(f"  Impact: {action['impact']}")

# Show implementation phases
for phase_key, phase in recommendations['implementation_guide'].items():
    print(f"\n{phase['title']}")
    print(f"Steps: {len(phase['steps'])}")
    for criterion in phase['success_criteria']:
        print(f"  ✓ {criterion}")
```

### Example 3: Compare Multiple Agents

```python
from agent_review_tool.tools import compare_agents

# Compare agents
comparison = compare_agents([
    "agents/customer_support.yaml",
    "agents/sales_assistant.yaml",
    "agents/hr_helper.yaml"
])

# Show best practices leader
leader = comparison['best_practices_leader']
print(f"Best Agent: {leader['name']} (Score: {leader['score']})")
print("Strengths:")
for strength in leader['strengths']:
    print(f"  - {strength}")

# Show common issues
print("\nCommon Issues Across All Agents:")
for issue in comparison['common_issues']:
    print(f"  - {issue['anti_pattern']} ({issue['occurrences']} agents)")
```

## Real-World Scenarios

### Scenario 1: Pre-Production Review

**Situation**: You've built a new agent and want to ensure it's production-ready.

```python
from agent_review_tool.tools import analyze_agent_config, generate_recommendations

# Analyze the agent
results = analyze_agent_config(config_path="new_agent.yaml")

# Check if production-ready
if results['overall_score'] >= 80 and results['critical_issues'] == 0:
    print("✅ Agent is production-ready!")
else:
    print("⚠️  Agent needs improvements before production")
    
    # Get recommendations
    recs = generate_recommendations(results)
    
    print(f"\nMust fix {recs['summary']['immediate_actions']} critical issues")
    print(f"Estimated effort: {recs['summary']['estimated_effort']}")
    
    # Show what to fix first
    for action in recs['priority_actions']:
        print(f"\n1. Fix: {action['anti_pattern']}")
        print(f"   {action['action']}")
```

### Scenario 2: Organizational Audit

**Situation**: You want to assess all agents in your organization.

```python
from agent_review_tool.tools import compare_agents
import glob

# Find all agent configs
agent_files = glob.glob("agents/**/*.yaml", recursive=True)

# Compare all agents
comparison = compare_agents(agent_files)

# Generate report
print(f"Total Agents Analyzed: {len(comparison['agents'])}")
print(f"\nAverage Score: {sum(a['score'] for a in comparison['agents']) / len(comparison['agents']):.1f}")

# Identify problem agents
problem_agents = [a for a in comparison['agents'] if a['score'] < 70]
print(f"\nAgents Needing Attention: {len(problem_agents)}")
for agent in problem_agents:
    print(f"  - {agent['name']}: {agent['score']}/100 ({agent['grade']})")

# Show organizational recommendations
print("\nOrganization-Wide Recommendations:")
for rec in comparison['recommendations']:
    print(f"  • {rec}")
```

### Scenario 3: Continuous Improvement

**Situation**: You want to track improvements over time.

```python
from agent_review_tool.tools import analyze_agent_config
import json
from datetime import datetime

def track_agent_health(agent_path, history_file="agent_history.json"):
    # Analyze current state
    results = analyze_agent_config(config_path=agent_path)
    
    # Load history
    try:
        with open(history_file, 'r') as f:
            history = json.load(f)
    except FileNotFoundError:
        history = []
    
    # Add current results
    history.append({
        'timestamp': datetime.now().isoformat(),
        'score': results['overall_score'],
        'grade': results['grade'],
        'critical_issues': results['critical_issues'],
        'high_priority': results['high_priority']
    })
    
    # Save history
    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)
    
    # Show trend
    if len(history) > 1:
        prev = history[-2]
        curr = history[-1]
        change = curr['score'] - prev['score']
        
        if change > 0:
            print(f"✅ Improvement: +{change} points")
        elif change < 0:
            print(f"⚠️  Regression: {change} points")
        else:
            print("➡️  No change")
    
    return results

# Track weekly
results = track_agent_health("my_agent.yaml")
```

### Scenario 4: CI/CD Integration

**Situation**: Automatically review agents in your CI/CD pipeline.

```python
#!/usr/bin/env python3
"""
CI/CD Agent Review Script
Add to your pipeline to enforce quality standards
"""

import sys
from agent_review_tool.tools import analyze_agent_config

def ci_review(agent_path, min_score=70, max_critical=0):
    """
    Review agent and fail CI if standards not met.
    """
    results = analyze_agent_config(config_path=agent_path)
    
    print(f"Agent Review Results:")
    print(f"  Score: {results['overall_score']}/100")
    print(f"  Grade: {results['grade']}")
    print(f"  Critical Issues: {results['critical_issues']}")
    
    # Check standards
    passed = True
    
    if results['overall_score'] < min_score:
        print(f"❌ FAIL: Score {results['overall_score']} below minimum {min_score}")
        passed = False
    
    if results['critical_issues'] > max_critical:
        print(f"❌ FAIL: {results['critical_issues']} critical issues found")
        passed = False
    
    if not passed:
        print("\nCritical Issues:")
        for finding in results['findings']:
            if finding['severity'] == 'critical':
                print(f"  - {finding['anti_pattern']}: {finding['issue']}")
        sys.exit(1)
    
    print("✅ PASS: Agent meets quality standards")
    return results

if __name__ == "__main__":
    ci_review(sys.argv[1] if len(sys.argv) > 1 else "agent.yaml")
```

## Interactive Agent Usage

### Using the Agent in watsonx Orchestrate

Once deployed, interact with the agent naturally:

**Example Conversation 1: Initial Analysis**
```
User: "Analyze my customer support agent configuration"

Agent: "I'll analyze your agent configuration for anti-patterns and 
optimization opportunities. Please provide the agent configuration 
file path or paste the YAML content."

User: [provides config]

Agent: "I've analyzed your Customer Support Agent. Here's what I found:

Overall Score: 75/100 (Grade: C - Fair)

Key Issues:
1. [HIGH] Monolithic Mega-Prompt: Your system prompt is 2,500 characters, 
   indicating over-reliance on instructions rather than system design.
   
2. [MEDIUM] Tool Soup: Agent has access to 12 tools, which may degrade 
   selection accuracy.

3. [MEDIUM] No Error Handling: Missing retry and recovery mechanisms.

Would you like me to generate a detailed implementation plan to address 
these issues?"
```

**Example Conversation 2: Comparison**
```
User: "Compare my three support agents and tell me which one is best"

Agent: "I'll compare your agents. Please provide the configuration files."

User: [provides 3 configs]

Agent: "Comparison Results:

Best Practices Leader: Premium Support Agent (Score: 85/100)
Strengths:
- Well-scoped tool access (6 tools)
- Proper error handling with retry logic
- Structured knowledge base with metadata

Common Issues Across All Agents:
- All three lack comprehensive testing strategies
- Two agents have oversized system prompts

Recommendation: Use Premium Support Agent as a template for the others. 
Focus on adding error handling to Basic Support Agent and reducing the 
prompt size in Enterprise Support Agent."
```

## Advanced Usage

### Custom Scoring Thresholds

```python
from agent_review_tool.tools import analyze_agent_config

def custom_evaluation(config_path, thresholds):
    """
    Evaluate agent against custom organizational standards.
    """
    results = analyze_agent_config(config_path=config_path)
    
    evaluation = {
        'meets_standards': True,
        'violations': []
    }
    
    # Check custom thresholds
    if results['overall_score'] < thresholds['min_score']:
        evaluation['meets_standards'] = False
        evaluation['violations'].append(
            f"Score {results['overall_score']} below minimum {thresholds['min_score']}"
        )
    
    if results['critical_issues'] > thresholds['max_critical']:
        evaluation['meets_standards'] = False
        evaluation['violations'].append(
            f"{results['critical_issues']} critical issues exceed limit {thresholds['max_critical']}"
        )
    
    # Check specific categories
    for finding in results['findings']:
        if finding['category'] in thresholds.get('blocked_categories', []):
            evaluation['meets_standards'] = False
            evaluation['violations'].append(
                f"Blocked category: {finding['category']} - {finding['anti_pattern']}"
            )
    
    return evaluation

# Example usage
thresholds = {
    'min_score': 80,
    'max_critical': 0,
    'blocked_categories': ['Security', 'Compliance']
}

eval_result = custom_evaluation("agent.yaml", thresholds)
```

### Batch Processing

```python
from agent_review_tool.tools import analyze_agent_config
import glob
import csv

def batch_analyze(pattern="agents/**/*.yaml", output_csv="results.csv"):
    """
    Analyze multiple agents and export results to CSV.
    """
    agent_files = glob.glob(pattern, recursive=True)
    results = []
    
    for agent_file in agent_files:
        try:
            analysis = analyze_agent_config(config_path=agent_file)
            results.append({
                'file': agent_file,
                'score': analysis['overall_score'],
                'grade': analysis['grade'],
                'critical': analysis['critical_issues'],
                'high': analysis['high_priority'],
                'medium': analysis['medium_priority']
            })
        except Exception as e:
            print(f"Error analyzing {agent_file}: {e}")
    
    # Export to CSV
    with open(output_csv, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    
    print(f"Analyzed {len(results)} agents, results saved to {output_csv}")
    return results

# Run batch analysis
batch_analyze()
```

## Tips and Best Practices

### 1. Regular Reviews
- Review agents before each production deployment
- Schedule monthly audits of all production agents
- Track scores over time to measure improvements

### 2. Use in Development
- Integrate into your development workflow
- Run analysis before code reviews
- Use as a learning tool for new team members

### 3. Customize for Your Organization
- Set minimum score thresholds based on your standards
- Define organization-specific anti-patterns
- Create templates based on high-scoring agents

### 4. Act on Recommendations
- Prioritize critical and high-severity issues
- Implement quick wins for immediate improvements
- Plan long-term improvements in sprints

### 5. Share Knowledge
- Use comparison results to identify best practices
- Create internal guidelines based on findings
- Share successful patterns across teams