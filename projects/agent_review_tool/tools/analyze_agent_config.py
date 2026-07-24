"""
Tool to analyze AI agent configurations and identify anti-patterns.

Based on best practices from production AI agent systems.

Supports the watsonx Orchestrate ADK agent YAML schema (field: 'instructions')
as well as legacy keys ('system_prompt', 'prompt') for compatibility.
"""

from ibm_watsonx_orchestrate.agent_builder.tools.python_tool import tool
import yaml
import json
from typing import Dict, List, Any, Optional
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema helpers — centralise field access so every analyzer uses the same
# normalised view of the config regardless of which key variant is present.
# ---------------------------------------------------------------------------

def _get_prompt(config: Dict) -> str:
    """Return the agent's instruction/prompt text.

    wxO ADK YAML uses 'instructions'.  Legacy/custom formats may use
    'system_prompt' or 'prompt'.  Returns an empty string when absent.
    """
    return config.get('instructions',
           config.get('system_prompt',
           config.get('prompt', '')))


def _has_prompt(config: Dict) -> bool:
    """True when any known prompt key is present in the config."""
    return any(k in config for k in ('instructions', 'system_prompt', 'prompt'))


def _get_kb_entries(config: Dict) -> list:
    """Return the knowledge_bases list (or a single-item list for dict form).

    wxO ADK YAML: knowledge_bases is a list of objects, each with at minimum
    a 'name' key.  Legacy/custom formats may store it as a plain dict.
    """
    raw = config.get('knowledge_bases', config.get('rag', config.get('retrieval', None)))
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    return []


@tool
def analyze_agent_config(
    config_path: Optional[str] = None,
    config_content: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze an AI agent configuration for anti-patterns and optimization opportunities.
    
    Args:
        config_path: Path to agent YAML configuration file
        config_content: Direct YAML/JSON content of agent configuration
        
    Returns:
        Dictionary containing analysis results with findings and recommendations
    """
    
    # Load configuration
    if config_path:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    elif config_content:
        try:
            config = yaml.safe_load(config_content)
        except:
            config = json.loads(config_content)
    else:
        return {
            "error": "Either config_path or config_content must be provided"
        }
    
    findings = []

    # Analyze based on the 6 core lessons
    all_module_findings = [
        # (label, findings_list)
        ("Prompt Design",       _analyze_prompt_design(config)),
        ("System Design",       _analyze_system_design(config)),
        ("Knowledge Mgmt",      _analyze_knowledge_management(config)),
        ("Testing Strategy",    _analyze_testing_strategy(config)),
        ("Performance Design",  _analyze_performance_design(config)),
        ("Context Usage",       _analyze_context_usage(config)),
    ]

    for _label, module_findings in all_module_findings:
        findings.extend(module_findings)

    score = _calculate_score(findings, config)
    
    return {
        "overall_score": score,
        "grade": _get_grade(score),
        "total_findings": len(findings),
        "critical_issues": len([f for f in findings if f['severity'] == 'critical']),
        "high_priority": len([f for f in findings if f['severity'] == 'high']),
        "medium_priority": len([f for f in findings if f['severity'] == 'medium']),
        "low_priority": len([f for f in findings if f['severity'] == 'low']),
        "findings": findings,
        "summary": _generate_summary(findings, score)
    }



# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

# Deduction per finding severity — applied per-finding, then capped per category.
_SEVERITY_DEDUCTION: Dict[str, int] = {
    "critical": 15,
    "high":     10,
    "medium":    3,
    "low":       0,
}

# Maximum deduction any single category can contribute.
# Prevents one bad module from dominating the score.
_MAX_DEDUCTION_PER_CATEGORY = 20

# Hard cap on the total deduction across all categories combined.
# Ensures the worst possible score is 30 (F), preserving grade-scale resolution.
_MAX_TOTAL_DEDUCTION = 70

# Good-practice bonus signals — presence reduces the effective deduction.
# Bonuses lower the deduction (floor 0); they cannot inflate a score above 100.
_BONUS_SIGNALS = [
    # Config key          Sub-key (None = top-level truthy check)
    ("error_handling",    None),
    ("validation",        None),
    ("guardrails",        None),
    ("retry",             None),
    ("fallback",          None),
]
_BONUS_PER_SIGNAL = 5
_MAX_BONUS        = 15


def _calculate_score(findings: List[Dict], config: Dict) -> int:
    """Compute the overall quality score (0–100).

    Scoring rules (Gap #4 fix):
    1. For every finding accumulate per-severity deduction points:
         critical → 15,  high → 10,  medium → 3,  low → 0
    2. Deductions are grouped by finding 'category'.  Each category is
       capped at _MAX_DEDUCTION_PER_CATEGORY (20 pts) so one bad module
       cannot zero the score.
    3. The sum of all capped category deductions is itself capped at
       _MAX_TOTAL_DEDUCTION (70 pts), keeping the worst possible score at 30.
    4. Good-practice signals (error_handling, validation, etc.) each award
       +5 bonus points, total bonus capped at _MAX_BONUS (15 pts).
       Bonuses *reduce the deduction* (floor 0) rather than inflating 100,
       so they reward improvement, not perfection.
    5. Final score = max(0, min(100, 100 - net_deduction)).
    """
    # Step 1 — accumulate raw deductions per category
    category_deductions: Dict[str, int] = {}
    for finding in findings:
        cat = finding.get("category", "General")
        sev = finding.get("severity", "low")
        pts = _SEVERITY_DEDUCTION.get(sev, 0)
        category_deductions[cat] = category_deductions.get(cat, 0) + pts

    # Step 2 — apply per-category cap, then global cap
    total_deduction = min(
        sum(min(d, _MAX_DEDUCTION_PER_CATEGORY) for d in category_deductions.values()),
        _MAX_TOTAL_DEDUCTION,
    )

    # Step 3 — good-practice bonuses
    bonus = 0
    for key, subkey in _BONUS_SIGNALS:
        if key in config:
            value = config[key]
            signal_present = (
                bool(value) if subkey is None
                else (isinstance(value, dict) and bool(value.get(subkey)))
            )
            if signal_present:
                bonus += _BONUS_PER_SIGNAL
    bonus = min(bonus, _MAX_BONUS)

    # Bonus for a well-scoped tool list (3–8 tools)
    tool_count = len(config.get("tools", []))
    if 3 <= tool_count <= 8:
        bonus = min(bonus + _BONUS_PER_SIGNAL, _MAX_BONUS)

    # Bonus for concise, non-empty instructions (100–1000 chars)
    prompt = _get_prompt(config)
    if 100 <= len(prompt) <= 1000:
        bonus = min(bonus + _BONUS_PER_SIGNAL, _MAX_BONUS)

    # Step 4 — bonuses reduce deduction (not inflate above 100)
    net_deduction = max(0, total_deduction - bonus)
    return max(0, min(100, 100 - net_deduction))



def _analyze_prompt_design(config: Dict) -> List[Dict]:
    """Analyze prompt design for anti-patterns (Lesson 1)."""
    findings = []

    prompt = _get_prompt(config)

    if _has_prompt(config):
        prompt_length = len(prompt)

        if prompt_length > 2000:
            findings.append({
                "category": "Prompt Design",
                "severity": "high",
                "anti_pattern": "Monolithic Mega-Prompt",
                "issue": f"Agent instructions are {prompt_length} characters long, indicating over-reliance on instructions",
                "recommendation": "Right-size the agent and prompt. Split capabilities across specialized agents or workflows with explicit coordination. Enforce boundaries in code, tools, and workflow logic rather than just wording.",
                "reference": "Lesson 1: Don't Mistake Prompting for Control"
            })

        # Check for excessive constraints in prompt
        constraint_keywords = ['must', 'always', 'never', 'only', 'exactly', 'strictly']
        constraint_count = sum(prompt.lower().count(kw) for kw in constraint_keywords)

        if constraint_count > 10:
            findings.append({
                "category": "Prompt Design",
                "severity": "medium",
                "anti_pattern": "Over-Constrained Prompting",
                "issue": f"Instructions contain {constraint_count} constraint keywords, attempting to force deterministic behavior",
                "recommendation": "Models approximate instructions, not execute them. Use system design (workflows, tool contracts, validation) to enforce behavior instead of piling on constraints.",
                "reference": "Lesson 1: Don't Mistake Prompting for Control"
            })

        # Check for vague, under-specified prompts
        if len(prompt) < 100 and 'tools' in config and len(config.get('tools', [])) > 3:
            findings.append({
                "category": "Prompt Design",
                "severity": "medium",
                "anti_pattern": "Under-Specified Prompt with Broad Autonomy",
                "issue": "Very short instructions with multiple tools suggests vague guidance with broad autonomy",
                "recommendation": "Give the agent a clear, focused job with a concise instruction set. Constrain action space through system design.",
                "reference": "Lesson 1: Don't Mistake Prompting for Control"
            })

    # Check agent scope
    if 'tools' in config:
        tool_count = len(config.get('tools', []))
        if tool_count > 10:
            findings.append({
                "category": "Prompt Design",
                "severity": "high",
                "anti_pattern": "Over-Specialized Agent",
                "issue": f"Agent has access to {tool_count} tools, suggesting over-broad scope",
                "recommendation": "Limit agent hierarchies to 2 levels max. Scope agents by use case domain rather than individual operations. Aim for focused capability, not fragmentation.",
                "reference": "Lesson 1: Don't Mistake Prompting for Control"
            })

    return findings


def _analyze_system_design(config: Dict) -> List[Dict]:
    """Analyze system design for anti-patterns (Lesson 2)."""
    findings = []

    # Check for business logic in prompts
    if _has_prompt(config):
        prompt = _get_prompt(config)
        business_logic_keywords = [
            'approval', 'validate', 'check if', 'verify', 'compliance',
            'rule', 'policy', 'must be', 'threshold', 'limit'
        ]
        
        logic_count = sum(1 for kw in business_logic_keywords if kw in prompt.lower())
        
        if logic_count >= 3:
            findings.append({
                "category": "System Design",
                "severity": "critical",
                "anti_pattern": "Agent-as-Business-Process Fallacy",
                "issue": "Business logic (approvals, validations, compliance rules) embedded in prompt text",
                "recommendation": "Put deterministic logic in workflows, code, and tool contracts. Use agents for judgment, ambiguity, and open-ended reasoning. Use workflows for order, control, approvals, rollback, and enforcement.",
                "reference": "Lesson 2: Stop Asking Prompts to Do the Job of Systems"
            })
    
    # Check for empty tools/collaborators that contradict the instructions
    if _has_prompt(config):
        prompt = _get_prompt(config)
        tools = config.get('tools', None)
        collaborators = config.get('collaborators', None)

        # Instructions reference tool usage but tools list is empty
        tool_reference_keywords = ['tool', 'invoke', 'call', 'use ', 'trigger', 'run ']
        mentions_tools = any(kw in prompt.lower() for kw in tool_reference_keywords)
        if mentions_tools and isinstance(tools, list) and len(tools) == 0:
            findings.append({
                "category": "System Design",
                "severity": "high",
                "anti_pattern": "Missing Tool Registrations",
                "issue": "Agent instructions reference tool usage but the tools list is empty — tools will never be invoked",
                "recommendation": "List every tool the agent needs under the 'tools' key. An agent cannot call tools that are not registered in its YAML.",
                "reference": "Lesson 2: Stop Asking Prompts to Do the Job of Systems"
            })

        # Instructions reference delegation/routing but collaborators list is empty
        collab_reference_keywords = ['delegate', 'route', 'hand off', 'escalate to', 'forward to', 'send to']
        mentions_collaborators = any(kw in prompt.lower() for kw in collab_reference_keywords)
        if mentions_collaborators and isinstance(collaborators, list) and len(collaborators) == 0:
            findings.append({
                "category": "System Design",
                "severity": "high",
                "anti_pattern": "Missing Collaborator Registrations",
                "issue": "Agent instructions reference delegating to other agents but the collaborators list is empty — delegation will never work",
                "recommendation": "List every collaborator agent under the 'collaborators' key. An agent cannot delegate to agents that are not registered.",
                "reference": "Lesson 2: Stop Asking Prompts to Do the Job of Systems"
            })

    # Check for tool soup anti-pattern
    if 'tools' in config:
        tools = config.get('tools', [])
        if len(tools) > 15:
            findings.append({
                "category": "System Design",
                "severity": "high",
                "anti_pattern": "Tool Soup",
                "issue": f"Agent has access to {len(tools)} tools, degrading selection accuracy",
                "recommendation": "Curate tool access aggressively. Agent should see only the tools it actually needs. Large tool catalogs increase confusion and mistakes.",
                "reference": "Lesson 2: Stop Asking Prompts to Do the Job of Systems"
            })
        
        # Check for large tool definitions
        tool_definition_size = len(str(tools))
        if tool_definition_size > 5000:
            findings.append({
                "category": "System Design",
                "severity": "medium",
                "anti_pattern": "Tool Data Overload",
                "issue": "Large tool definitions consume substantial context and increase cost",
                "recommendation": "Keep tool definitions concise. Large schemas sent repeatedly across turns waste tokens and degrade performance.",
                "reference": "Lesson 2: Stop Asking Prompts to Do the Job of Systems"
            })
    
    return findings


def _analyze_knowledge_management(config: Dict) -> List[Dict]:
    """Analyze knowledge management for anti-patterns (Lesson 3).

    Uses real wxO ADK KB YAML fields:
      - 'description' presence as a proxy for curation quality
      - 'retrieval_confidence_threshold' / 'max_docs_passed_to_llm' for tuning
      - 'top_k' / 'max_results' for over-retrieval
      - absence of any 'documents' / 'path' entries as a signal of an empty KB
    """
    findings = []

    kb_entries = _get_kb_entries(config)

    if kb_entries:
        for kb in kb_entries:
            if not isinstance(kb, dict):
                continue

            kb_name = kb.get('name', '<unnamed>')

            # Gap #5 fix: check real ADK fields, not fictional 'structured'/'metadata'
            # A KB without a description is a signal it has not been curated.
            if not kb.get('description', '').strip():
                findings.append({
                    "category": "Knowledge Management",
                    "severity": "high",
                    "anti_pattern": "Unstructured Data Assumption",
                    "issue": f"Knowledge base '{kb_name}' has no description — likely not curated for agent consumption",
                    "recommendation": "Add a clear description to every knowledge base. Curate content with metadata, ownership, and versioning. Use semantic retrieval for contextual lookup, databases/APIs for structured facts, and targeted extraction for documents.",
                    "reference": "Lesson 3: RAG Does Not Clean Up Bad Knowledge"
                })

            # A KB with no documents/path entries is empty or misconfigured
            has_documents = bool(kb.get('documents') or kb.get('path') or kb.get('urls'))
            if not has_documents:
                findings.append({
                    "category": "Knowledge Management",
                    "severity": "medium",
                    "anti_pattern": "Empty Knowledge Base",
                    "issue": f"Knowledge base '{kb_name}' has no documents, paths, or URLs configured",
                    "recommendation": "Ensure the knowledge base is populated with relevant, curated content before attaching it to an agent.",
                    "reference": "Lesson 3: RAG Does Not Clean Up Bad Knowledge"
                })

            # Over-retrieval check using real ADK field names
            top_k = kb.get('top_k', kb.get('max_results', kb.get('max_docs_passed_to_llm', 0)))
            if isinstance(top_k, int) and top_k > 10:
                findings.append({
                    "category": "Context Management",
                    "severity": "medium",
                    "anti_pattern": "Over-Retrieved Knowledge",
                    "issue": f"Knowledge base '{kb_name}' retrieves {top_k} passages, compounding token costs",
                    "recommendation": "Curate knowledge for targeted retrieval. Over-retrieved passages are carried forward turn after turn, inflating context costs.",
                    "reference": "Lesson 6: Don't Use More Context to Compensate for Bad Design"
                })

    # Check if RAG is being used as a band-aid (instruction text signal)
    if _has_prompt(config):
        prompt = _get_prompt(config)
        if 'knowledge' in prompt.lower() and ('messy' in prompt.lower() or 'outdated' in prompt.lower()):
            findings.append({
                "category": "Knowledge Management",
                "severity": "critical",
                "anti_pattern": "RAG Will Fix Disorganized Knowledge",
                "issue": "Instructions suggest reliance on RAG to handle messy or outdated knowledge",
                "recommendation": "RAG does not fix knowledge problems — it amplifies them. Clean, structure, and curate knowledge first.",
                "reference": "Lesson 3: RAG Does Not Clean Up Bad Knowledge"
            })

    return findings


def _analyze_testing_strategy(config: Dict) -> List[Dict]:
    """Analyze testing strategy indicators (Lesson 4)."""
    findings = []
    
    # Check for error handling configuration
    has_error_handling = (
        'error_handling' in config or
        'retry' in config or
        'fallback' in config or
        'recovery' in config
    )
    
    if not has_error_handling:
        findings.append({
            "category": "Testing & Resilience",
            "severity": "high",
            "anti_pattern": "Happy Path Engineering",
            "issue": "No error handling, retry, or recovery mechanisms configured",
            "recommendation": "Evaluate the system under conditions that actually matter: ambiguity, conflicting instructions, tool failures, multi-turn corrections, non-cooperative inputs, adversarial testing. Measure whether the system can recover, stay bounded, and remain useful when things go wrong.",
            "reference": "Lesson 4: Demo Success Proves Almost Nothing"
        })
    
    # Check for validation mechanisms
    has_validation = (
        'validation' in config or
        'guardrails' in config or
        'constraints' in config
    )
    
    if not has_validation:
        findings.append({
            "category": "Testing & Resilience",
            "severity": "medium",
            "anti_pattern": "Demo-Grade Agent in Production",
            "issue": "No validation or guardrails configured for production use",
            "recommendation": "Without recovery training, agents achieve success rates below 50% when tools fail. Test with tool failures, ambiguous inputs, and adversarial scenarios.",
            "reference": "Lesson 4: Demo Success Proves Almost Nothing"
        })
    
    return findings


def _analyze_performance_design(config: Dict) -> List[Dict]:
    """Analyze performance and latency design (Lesson 5)."""
    findings = []

    # Check for nested planning or excessive loops
    if _has_prompt(config):
        prompt = _get_prompt(config)
        planning_keywords = ['plan', 'think', 'reason', 'analyze', 'consider']
        planning_count = sum(1 for kw in planning_keywords if kw in prompt.lower())
        
        if planning_count >= 3:
            findings.append({
                "category": "Performance",
                "severity": "high",
                "anti_pattern": "Responsiveness Afterthought",
                "issue": "Multiple planning/reasoning steps in prompt suggest nested loops that add latency",
                "recommendation": "Treat responsiveness as a design constraint from day one. Keep prompts lean, reduce unnecessary model calls, avoid nested planning when a direct path will do, filter tool outputs at the source, parallelize only where it genuinely helps.",
                "reference": "Lesson 5: Latency Is an Architecture Problem, Not Just a Model Problem"
            })
    
    # Check for excessive tool calls
    if 'max_iterations' in config:
        max_iter = config.get('max_iterations', 0)
        if max_iter > 10:
            findings.append({
                "category": "Performance",
                "severity": "medium",
                "anti_pattern": "Tool Data Overload",
                "issue": f"Max iterations set to {max_iter}, allowing many sequential tool calls",
                "recommendation": "Each model call adds 200-2000ms latency. Nested planning loops push latency beyond acceptable SLAs. Reduce unnecessary model calls.",
                "reference": "Lesson 5: Latency Is an Architecture Problem, Not Just a Model Problem"
            })
    
    # Check for large context windows
    if 'max_tokens' in config or 'context_window' in config:
        max_tokens = config.get('max_tokens', config.get('context_window', 0))
        if max_tokens > 8000:
            findings.append({
                "category": "Performance",
                "severity": "medium",
                "anti_pattern": "Firehose Effect",
                "issue": f"Large context window ({max_tokens} tokens) may cause context exhaustion and prefill latency",
                "recommendation": "Tools returning megabytes when only kilobytes are needed create the 'Firehose Effect'. Filter data before it reaches the model.",
                "reference": "Lesson 5: Latency Is an Architecture Problem, Not Just a Model Problem"
            })
    
    return findings


def _analyze_context_usage(config: Dict) -> List[Dict]:
    """Analyze context usage patterns (Lesson 6).

    Note: over-retrieval (top_k > 10) is emitted by _analyze_knowledge_management
    so it is not duplicated here.
    """
    findings = []

    # Check for oversized instructions
    if _has_prompt(config):
        prompt = _get_prompt(config)
        prompt_length = len(prompt)

        if prompt_length > 3000:
            findings.append({
                "category": "Context Management",
                "severity": "high",
                "anti_pattern": "Unbounded Execution Cost",
                "issue": f"Oversized agent instructions ({prompt_length} chars) drive up costs through repeated transmission",
                "recommendation": "Design for precision, not volume. Curate knowledge so retrieval can return smaller, more targeted passages. Filter data before it reaches the model. Use the smallest useful context, toolset, and model for the task.",
                "reference": "Lesson 6: Don't Use More Context to Compensate for Bad Design"
            })

        # Check for "give the model everything" approach
        if 'all information' in prompt.lower() or 'everything' in prompt.lower():
            findings.append({
                "category": "Context Management",
                "severity": "critical",
                "anti_pattern": "Give the Model Everything",
                "issue": "Instructions suggest providing maximum context as a strategy",
                "recommendation": "'Give the model everything' is not a strategy — it's an expensive way to hide poor knowledge design. More tokens do not mean more value; they often mean the system is compensating for weak structure upstream.",
                "reference": "Lesson 6: Don't Use More Context to Compensate for Bad Design"
            })

    # Check for large tool schemas
    if 'tools' in config:
        tools = config.get('tools', [])
        tool_str = str(tools)
        if len(tool_str) > 10000:
            findings.append({
                "category": "Context Management",
                "severity": "high",
                "anti_pattern": "Unbounded Execution Cost",
                "issue": "Large tool definitions sent repeatedly across turns waste tokens",
                "recommendation": "Costs accumulate through oversized models, repeated retrieval, re-planning loops, and oversized tool catalogs. Use the smallest useful toolset.",
                "reference": "Lesson 6: Don't Use More Context to Compensate for Bad Design"
            })

    return findings


def _get_grade(score: int) -> str:
    """Convert numeric score to letter grade."""
    if score >= 90:
        return "A (Excellent)"
    elif score >= 80:
        return "B (Good)"
    elif score >= 70:
        return "C (Fair)"
    elif score >= 60:
        return "D (Needs Improvement)"
    else:
        return "F (Critical Issues)"


def _generate_summary(findings: List[Dict], score: int) -> str:
    """Generate executive summary of findings."""
    if score >= 90:
        summary = "Agent configuration follows best practices with minimal issues."
    elif score >= 70:
        summary = "Agent configuration is generally sound but has some optimization opportunities."
    elif score >= 50:
        summary = "Agent configuration has significant issues that should be addressed before production."
    else:
        summary = "Agent configuration has critical issues that will likely cause production failures."
    
    # Add category breakdown
    categories = {}
    for finding in findings:
        cat = finding['category']
        categories[cat] = categories.get(cat, 0) + 1
    
    if categories:
        summary += "\n\nIssues by category: " + ", ".join([f"{cat} ({count})" for cat, count in categories.items()])
    
    return summary

# Made with Bob
