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

    # Analyze based on all anti-pattern categories from Parts 1–6
    all_module_findings = [
        # (label, findings_list)
        ("Prompt Design",       _analyze_prompt_design(config)),
        ("System Design",       _analyze_system_design(config)),
        ("Autonomy & Control",  _analyze_autonomy_control(config)),
        ("Knowledge Mgmt",      _analyze_knowledge_management(config)),
        ("Testing Strategy",    _analyze_testing_strategy(config)),
        ("Performance Design",  _analyze_performance_design(config)),
        ("Context Usage",       _analyze_context_usage(config)),
        ("MCP & Tool Design",   _analyze_mcp_tool_design(config)),
        ("Observability",       _analyze_observability(config)),
        ("Model Selection",     _analyze_model_selection(config)),
        ("Guidelines",          _analyze_guidelines(config)),
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

    # Bonus for well-authored guidelines (present, concise conditions, no tool-output matching)
    guidelines = config.get("guidelines", [])
    if isinstance(guidelines, list) and 0 < len(guidelines) <= 10:
        avg_cond_len = (
            sum(len(g.get("condition", "")) for g in guidelines if isinstance(g, dict))
            / len(guidelines)
        )
        if avg_cond_len <= 120:
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



# ---------------------------------------------------------------------------
# Autonomy & Control analysis (Part 1 AP-04, Part 5 AP-28/AP-29)
# ---------------------------------------------------------------------------

def _analyze_autonomy_control(config: Dict) -> List[Dict]:
    """Detect all-or-nothing autonomy and natural-language workflow engine anti-patterns."""
    findings = []

    # AP-04: All-or-Nothing Autonomy — no autonomy controls at all
    has_hitl = any(k in config for k in ('human_in_the_loop', 'hitl', 'approval', 'require_confirmation'))
    has_autonomy_level = any(k in config for k in ('autonomy_level', 'autonomy', 'max_autonomy'))
    has_guardrails = 'guardrails' in config

    if not has_hitl and not has_autonomy_level and not has_guardrails:
        findings.append({
            "category": "Autonomy & Control",
            "severity": "medium",
            "anti_pattern": "All-or-Nothing Autonomy",
            "issue": "No autonomy controls, approval gates, or HITL configuration found. Without risk-weighted autonomy controls, agents may act on high-stakes operations without oversight.",
            "recommendation": "Make autonomy intentional and risk-weighted: autonomous for low-risk reads, notify for medium-risk writes, require explicit confirmation for high-risk/destructive operations. Add guardrails and consider HITL for high-stakes workflow steps.",
            "reference": "AP-04: All-or-Nothing Autonomy (Part 1 — Architectural Pitfalls)"
        })

    # AP-28/AP-29: Natural Language Workflow Engine — business process logic in instructions
    if _has_prompt(config):
        prompt = _get_prompt(config)
        workflow_keywords = [
            'step 1', 'step 2', 'step 3', 'first,', 'then,', 'finally,',
            'in order', 'sequentially', 'approval', 'compliance', 'audit trail',
            'rollback', 'retry', 'escalate', 'on failure'
        ]
        workflow_hits = sum(1 for kw in workflow_keywords if kw in prompt.lower())
        if workflow_hits >= 4:
            findings.append({
                "category": "Autonomy & Control",
                "severity": "critical",
                "anti_pattern": "Natural Language Workflow Engine",
                "issue": f"Instructions contain {workflow_hits} workflow-engine keywords (step sequences, approval/compliance/retry logic), suggesting business process logic encoded in the prompt.",
                "recommendation": "Prompts approximate workflow steps — they do not execute them reliably. IFBench shows best frontier models fail 17–38% of even simple instruction-following tasks. Move approval gates, compliance rules, retry logic, and ordered sequences to a workflow engine (watsonx Orchestrate Agentic Workflow, IBM BAW). The agent should be a participant in a workflow, not the workflow itself.",
                "reference": "AP-28: Natural Language Workflow Engine (Part 5 — The Illusion of Control)"
            })

    # AP-05: Passing verbatim-required content through model
    if _has_prompt(config):
        prompt = _get_prompt(config)
        verbatim_keywords = [
            'verbatim', 'exact text', 'do not change', 'word for word',
            'legal disclaimer', 'disclosure', 'regulatory text', 'compliance text',
            'copy exactly', 'reproduce exactly'
        ]
        verbatim_hits = sum(1 for kw in verbatim_keywords if kw in prompt.lower())
        if verbatim_hits >= 2:
            findings.append({
                "category": "Autonomy & Control",
                "severity": "high",
                "anti_pattern": "Verbatim Content Routed Through LLM",
                "issue": "Instructions attempt to make the agent reproduce exact/verbatim content. LLMs paraphrase and rewrite — even strict instructions cannot prevent subtle alterations of mandated text.",
                "recommendation": "Route verbatim-required content (legal disclaimers, regulatory text) around the LLM, not through it: use tools that generate PDFs or push directly to regulated channels, HITL workflow blocks that surface exact content, or MCP audience annotations marking responses as pass-through for the end user.",
                "reference": "AP-05: Passing As-Is Content Through the Model (Part 1 — Architectural Pitfalls)"
            })

    return findings


# ---------------------------------------------------------------------------
# MCP & Tool Design analysis (Part 4 AP-20–27)
# ---------------------------------------------------------------------------

def _analyze_mcp_tool_design(config: Dict) -> List[Dict]:
    """Detect MCP and tool design anti-patterns from Part 4."""
    findings = []

    tools = config.get('tools', [])
    if not tools:
        return findings  # nothing to check without tool definitions

    # AP-20/AP-21: Glorified API Wrapper / Raw Schema Leakage
    # Tools named with HTTP verb prefixes or raw query/schema parameters suggest API exposure
    api_wrapper_indicators = ['odata_', 'rest_', 'http_', 'query_raw', 'execute_sql',
                              'execute_query', 'execute_request', 'raw_request', 'api_call']
    api_wrapper_tools = []
    for t in tools:
        tool_name = t if isinstance(t, str) else (t.get('name', '') if isinstance(t, dict) else '')
        if any(tool_name.lower().startswith(ind) or tool_name.lower() == ind.rstrip('_')
               for ind in api_wrapper_indicators):
            api_wrapper_tools.append(tool_name)

    if api_wrapper_tools:
        findings.append({
            "category": "MCP & Tool Design",
            "severity": "high",
            "anti_pattern": "MCP as a Glorified API Wrapper",
            "issue": f"Tool(s) detected with raw API naming patterns: {api_wrapper_tools}. These expose API primitives instead of business capabilities, forcing the agent to act as an API client.",
            "recommendation": "Apply the Agent-Ready Tool Facade Pattern: wrap raw API operations behind intent-driven business capabilities. Replace odata_create(entity_set, payload) with create_purchase_order(vendor_id, items, delivery_date). Good tools reduce the burden on the model; bad tools amplify it.",
            "reference": "AP-20: MCP as a Glorified API Wrapper (Part 4 — MCP Tools & Integration)"
        })

    # AP-23: God-Mode Tool — look for overpowered tool names
    god_mode_indicators = ['execute_sql', 'execute_query', 'execute_command', 'run_script',
                           'eval_', 'exec_', 'kubectl_', 'delete_all', 'drop_', 'truncate_',
                           'admin_', 'superuser_', 'unrestricted_']
    god_mode_tools = []
    for t in tools:
        tool_name = t if isinstance(t, str) else (t.get('name', '') if isinstance(t, dict) else '')
        if any(ind in tool_name.lower() for ind in god_mode_indicators):
            god_mode_tools.append(tool_name)

    if god_mode_tools:
        findings.append({
            "category": "MCP & Tool Design",
            "severity": "critical",
            "anti_pattern": "God-Mode Tool (Overpowered Tool)",
            "issue": f"Tool(s) with broad/unrestricted execution capability detected: {god_mode_tools}. These turn agents into security vulnerabilities with no input validation or domain constraints.",
            "recommendation": "Apply least privilege: read-only by default, explicit enable flags for destructive operations, input validation inside the tool, and audit logging for all write operations.",
            "reference": "AP-23: God-Mode MCP Tool (Part 4 — MCP Tools & Integration)"
        })

    # AP-25: Kitchen Sink Server — very large tool count signals bundled MCP servers
    if len(tools) > 20:
        findings.append({
            "category": "MCP & Tool Design",
            "severity": "high",
            "anti_pattern": "Kitchen Sink Server",
            "issue": f"Agent has access to {len(tools)} tools. With 50+ MCP tools, definitions consume ~72K tokens upfront (60% of a 128K context window). A 4-turn conversation can burn 288K tokens on tool definitions alone.",
            "recommendation": "Scope tool catalogs by user role, task domain, and permissions. For production agents, build a business capability layer on top of generic MCP servers. Separate agents with focused tool sets serve different use cases better than one mega-catalog.",
            "reference": "AP-25: Kitchen Sink MCP Server (Part 4 — MCP Tools & Integration)"
        })

    # AP-22: Wishful Delegation — agent instructions reference complex multi-step tool usage
    if _has_prompt(config):
        prompt = _get_prompt(config)
        delegation_keywords = ['discover', 'fetch metadata', 'determine the schema',
                               'find the entity', 'construct the payload', 'look up the id first']
        delegation_hits = sum(1 for kw in delegation_keywords if kw in prompt.lower())
        if delegation_hits >= 2:
            findings.append({
                "category": "MCP & Tool Design",
                "severity": "medium",
                "anti_pattern": "Wishful Delegation",
                "issue": "Instructions require multi-step reasoning chains (discover schema → construct payload → execute) before tools can be used, pushing system design responsibility onto the LLM.",
                "recommendation": "Encode multi-step complexity inside the tool implementation. The agent should call create_purchase_order(vendor_id, items), not chain: discover_services → fetch_metadata → build_payload → execute_odata.",
                "reference": "AP-22: Wishful Delegation to MCP Tools (Part 4 — MCP Tools & Integration)"
            })

    return findings


# ---------------------------------------------------------------------------
# Observability analysis (Part 2 AP-10)
# ---------------------------------------------------------------------------

def _analyze_observability(config: Dict) -> List[Dict]:
    """Detect missing observability and tracing configuration."""
    findings = []

    has_observability = any(k in config for k in (
        'logging', 'tracing', 'observability', 'monitoring', 'telemetry',
        'audit', 'audit_log', 'traces'
    ))

    # Check for references to external/MCP tools — these need observability most
    has_external_tools = False
    tools = config.get('tools', [])
    mcp_indicators = ['mcp', 'external', 'third_party', 'integration', 'connector']
    for t in tools:
        tool_name = t if isinstance(t, str) else (t.get('name', '') if isinstance(t, dict) else '')
        if any(ind in tool_name.lower() for ind in mcp_indicators):
            has_external_tools = True
            break

    if not has_observability and (len(tools) > 3 or has_external_tools):
        findings.append({
            "category": "Observability",
            "severity": "medium",
            "anti_pattern": "Blind Trust in External Components (No Observability)",
            "issue": "No logging, tracing, or observability configuration found. Without instrumentation, when failures occur (bad outputs, latency spikes, cost surges) you cannot answer: What happened? Why? How to fix?",
            "recommendation": "Add an instrumentation layer that captures inputs, outputs, latency, and errors for every tool call. OWASP Top 10 for Agentic Applications 2026 (ASI02, ASI04) identifies unobserved tool usage as a primary attack surface. Treat external MCP servers as untrusted until verified.",
            "reference": "AP-10: Blind Trust in External Components (Part 2 — Tooling, Observability, Scale)"
        })

    return findings


# ---------------------------------------------------------------------------
# Model Selection analysis (Part 6 AP-30, AP-33)
# ---------------------------------------------------------------------------

def _analyze_model_selection(config: Dict) -> List[Dict]:
    """Detect model selection anti-patterns from Part 6."""
    findings = []

    # AP-33: Context Length Capacity Fallacy
    max_tokens = config.get('max_tokens', config.get('context_window', config.get('context_length', 0)))
    if isinstance(max_tokens, int) and max_tokens >= 100000:
        findings.append({
            "category": "Model Selection",
            "severity": "medium",
            "anti_pattern": "Context Length Capacity Fallacy",
            "issue": f"Context window set to {max_tokens:,} tokens. A large context window is NOT equivalent to reliable working memory. AI-Needle benchmark (July 2026): best frontier model (Claude Opus 4.5) achieves only 74% accuracy at deep context retrieval — failing more than 1-in-4 times on the simplest long-context task.",
            "recommendation": "Context window size is a hard ceiling on input length, not a measure of reliable working memory. Position critical instructions (current task, active tool schemas) early in context. Use retrieval to bring relevant content into a shorter, well-structured context rather than stuffing everything in. Evaluate long-context behavior on your actual task structure.",
            "reference": "AP-33: Context Length Capacity Fallacy (Part 6 — Model Selection)"
        })

    # AP-30: Benchmark-Only Model Selection — detect if a specific model is hard-coded
    model = config.get('model', config.get('llm', config.get('model_id', '')))
    if isinstance(model, str) and model:
        # Check if the model selection appears to be purely name-based without operational notes
        # We can only flag this if it's combined with other signals (e.g., very large context)
        if max_tokens and isinstance(max_tokens, int) and max_tokens >= 200000:
            findings.append({
                "category": "Model Selection",
                "severity": "low",
                "anti_pattern": "Benchmark-Only Model Selection Risk",
                "issue": f"Model '{model}' is configured with a very large context window ({max_tokens:,} tokens). Verify this is intentional and that the model has been evaluated on your actual production workload — not just leaderboard benchmarks.",
                "recommendation": "Evaluate models on the dimensions your system actually requires: latency, cost, tool-calling accuracy, structured output fidelity, context length, and deployment constraints. The era where 'just use the best model' was a safe architectural decision is over — the performance gap between frontier models has almost closed, but cost and latency differences remain enormous.",
                "reference": "AP-30: Benchmark-Only Model Selection (Part 6 — Model Selection)"
            })

    return findings



# ---------------------------------------------------------------------------
# Guidelines analysis
# ---------------------------------------------------------------------------

# Tokens that indicate a condition is matching on prior tool/agent output
# rather than on the user's current intent.
_OUTPUT_MATCH_TOKENS = [
    '⚠️', 'confirmation required', 're-type', 'collaborator response',
    'tool output', 'previous response', 'assistant said', 'agent said',
    'the response contains', 'response includes',
]

# Tokens that indicate keyword-list / enumeration padding rather than
# a concise semantic condition.
_KEYWORD_LIST_TOKENS = ['keywords:', 'note:', 'includes:', 'matches:', 'e.g.,', 'e.g.:']


# Condition words / phrases that indicate the guideline fires universally
# (every turn, regardless of what the user says) and therefore belongs in
# the instructions block rather than behind a classifier call.
_UNCONDITIONAL_TOKENS = [
    'always', 'every time', 'at all times', 'for all', 'whenever possible',
    'in all cases', 'regardless', 'by default', 'never ', 'do not ',
    'make sure', 'ensure that', 'remember to',
]

# Condition words that indicate a tone / persona / style guideline.
# These are pure behavioral defaults — no classifier is needed to route them.
_PERSONA_STYLE_TOKENS = [
    'politely', 'formally', 'professionally', 'friendly', 'concise',
    'brief', 'empathetic', 'tone', 'language style', 'respond in',
    'format your', 'use formal', 'use simple', 'use plain', 'be helpful',
    'be respectful', 'be concise', 'be professional', 'be polite',
]


def _analyze_guidelines(config: Dict) -> List[Dict]:
    """Analyze the guidelines section for anti-patterns.

    Checks:
    1. Verbose / mega-condition — condition text is too long (>150 chars).
    2. Keyword-list padding — condition enumerates keywords instead of
       expressing user intent semantically.
    3. Tool-output matching — condition checks for content in prior tool or
       collaborator responses rather than on user intent; causes the classifier
       to re-run after every tool call in the ReAct loop.
    4. Too many guidelines — large lists inflate the classifier prompt that
       WxO sends before every agent loop iteration.
    5. Missing action or tool — a guideline with neither 'action' nor 'tool'
       is a no-op and wastes a classifier slot.
    6. Condition text duplicated in instructions — the same routing logic
       appears in both the guidelines and the free-form instructions block,
       so it is paid for twice per turn.
    7. Instruction-suitable guidelines — guidelines that have no tool binding
       and whose condition is unconditional or describes persona/tone/style;
       these waste a classifier LLM call that instructions could replace for free.
    """
    findings = []
    guidelines = config.get("guidelines", [])

    if not isinstance(guidelines, list) or len(guidelines) == 0:
        return findings  # no guidelines configured — nothing to check

    # ------------------------------------------------------------------ #
    # Check 1 & 2: verbose conditions / keyword-list padding
    # ------------------------------------------------------------------ #
    verbose_ids = []
    keyword_padded_ids = []

    for g in guidelines:
        if not isinstance(g, dict):
            continue
        name = g.get("display_name") or g.get("id") or "<unnamed>"
        condition = g.get("condition", "")

        if len(condition) > 150:
            verbose_ids.append((name, len(condition)))

        cond_lower = condition.lower()
        if any(tok in cond_lower for tok in _KEYWORD_LIST_TOKENS):
            keyword_padded_ids.append(name)

    if verbose_ids:
        details = "; ".join(f"'{n}' ({c} chars)" for n, c in verbose_ids)
        findings.append({
            "category": "Guidelines",
            "severity": "high",
            "anti_pattern": "Verbose Guideline Conditions",
            "issue": (
                f"{len(verbose_ids)} guideline condition(s) exceed 150 characters: {details}. "
                "The WxO runtime sends ALL condition strings to the classifier LLM on every "
                "turn — length directly drives token cost and prefill latency."
            ),
            "recommendation": (
                "Shorten each condition to one sentence of user intent (target ≤100 chars). "
                "Move keyword lists, NOTE clauses, and disambiguation text into the guideline's "
                "'action' field or the agent's 'instructions' block — the classifier only needs "
                "enough to match, not to route."
            ),
            "reference": "Guidelines Performance: ADK docs warn guidelines add an LLM call before every agent loop"
        })

    if keyword_padded_ids:
        details = ", ".join(f"'{n}'" for n in keyword_padded_ids)
        findings.append({
            "category": "Guidelines",
            "severity": "medium",
            "anti_pattern": "Keyword-List Padding in Conditions",
            "issue": (
                f"Guideline condition(s) {details} use keyword enumerations or NOTE clauses "
                "('Keywords:', 'NOTE:', 'e.g.,') inside the condition text. "
                "This inflates the classifier prompt and turns semantic matching into "
                "brittle keyword matching."
            ),
            "recommendation": (
                "Express conditions as a single natural-language sentence describing user intent. "
                "Example: 'The user asks to list or investigate jobs or job failures.' "
                "Keyword lists and disambiguation notes belong in the 'action' field, not the condition."
            ),
            "reference": "Guidelines Performance: Condition text is re-sent to the classifier LLM on every turn"
        })

    # ------------------------------------------------------------------ #
    # Check 3: tool-output / history matching
    # ------------------------------------------------------------------ #
    output_matching_ids = []
    for g in guidelines:
        if not isinstance(g, dict):
            continue
        name = g.get("display_name") or g.get("id") or "<unnamed>"
        condition = g.get("condition", "").lower()
        if any(tok in condition for tok in _OUTPUT_MATCH_TOKENS):
            output_matching_ids.append(name)

    if output_matching_ids:
        details = ", ".join(f"'{n}'" for n in output_matching_ids)
        findings.append({
            "category": "Guidelines",
            "severity": "high",
            "anti_pattern": "Tool-Output Matching in Conditions",
            "issue": (
                f"Guideline condition(s) {details} match on prior tool/collaborator output "
                "content (e.g., checking for '⚠️', 'Confirmation Required', or 'collaborator "
                "response' in the history). The WxO classifier re-evaluates ALL guidelines "
                "after each tool result is appended to the conversation — this causes the "
                "classifier to fire extra times per turn, adding latency on every ReAct loop."
            ),
            "recommendation": (
                "Conditions should match on the USER's current intent, not on prior tool output. "
                "State-machine concerns (e.g., 'user is confirming a previously prompted command') "
                "belong in the agent's 'instructions' block or in a dedicated confirmation-routing "
                "tool — not in a guideline condition that is re-evaluated every loop iteration."
            ),
            "reference": "Guidelines Performance: Classifier re-runs after each tool call when conditions reference history content"
        })

    # ------------------------------------------------------------------ #
    # Check 4: too many guidelines
    # ------------------------------------------------------------------ #
    if len(guidelines) > 10:
        findings.append({
            "category": "Guidelines",
            "severity": "medium",
            "anti_pattern": "Guideline Catalog Overload",
            "issue": (
                f"Agent has {len(guidelines)} guidelines. The WxO runtime sends all condition "
                "strings to the classifier LLM before every agent loop iteration — a large "
                "catalog inflates the classifier prompt on every turn."
            ),
            "recommendation": (
                "Aim for ≤8 guidelines per agent. Consider whether some conditions should be "
                "merged, moved into the agent's 'instructions', or handled by splitting into "
                "specialised collaborator agents with their own smaller guideline sets."
            ),
            "reference": "ADK Performance Guide: Guidelines add an LLM call before the agent loop starts"
        })

    # ------------------------------------------------------------------ #
    # Check 5: no-op guidelines (neither action nor tool)
    # ------------------------------------------------------------------ #
    noop_ids = []
    for g in guidelines:
        if not isinstance(g, dict):
            continue
        name = g.get("display_name") or g.get("id") or "<unnamed>"
        has_action = bool(g.get("action", "").strip())
        has_tool = bool(g.get("tool", "").strip())
        if not has_action and not has_tool:
            noop_ids.append(name)

    if noop_ids:
        details = ", ".join(f"'{n}'" for n in noop_ids)
        findings.append({
            "category": "Guidelines",
            "severity": "medium",
            "anti_pattern": "No-Op Guideline",
            "issue": (
                f"Guideline(s) {details} have neither an 'action' nor a 'tool' field. "
                "They consume a classifier slot on every turn but trigger no behaviour when matched."
            ),
            "recommendation": (
                "Every guideline must specify at least one of: 'action' (natural-language "
                "instruction to follow) or 'tool' (tool name to invoke). Remove or complete "
                "these no-op entries."
            ),
            "reference": "ADK build_agent: 'Provide at least one of action or tool'"
        })

    # ------------------------------------------------------------------ #
    # Check 6: routing logic duplicated between guidelines and instructions
    # ------------------------------------------------------------------ #
    if _has_prompt(config) and guidelines:
        prompt = _get_prompt(config).lower()
        duplicated = []
        for g in guidelines:
            if not isinstance(g, dict):
                continue
            name = g.get("display_name") or g.get("id") or "<unnamed>"
            condition = g.get("condition", "")
            # Take the first 6 meaningful words of the condition as a fingerprint
            words = [w for w in condition.lower().split() if len(w) > 3][:6]
            if len(words) >= 3 and all(w in prompt for w in words):
                duplicated.append(name)

        if duplicated:
            details = ", ".join(f"'{n}'" for n in duplicated)
            findings.append({
                "category": "Guidelines",
                "severity": "low",
                "anti_pattern": "Routing Logic Duplicated in Instructions",
                "issue": (
                    f"Guideline condition(s) {details} appear to be restated inside the "
                    "agent's instructions block. This means the same routing logic is paid "
                    "for twice per turn: once in the classifier call and once in the main "
                    "agent loop prompt."
                ),
                "recommendation": (
                    "Choose one place for each routing rule. Use guidelines for structured, "
                    "rule-based routing (they get classifier pre-filtering). Use the instructions "
                    "block for general reasoning guidance. Avoid copying condition text verbatim "
                    "into both."
                ),
                "reference": "Guidelines Performance: Classifier output is re-injected into the main agent prompt"
            })

    # ------------------------------------------------------------------ #
    # Check 7: guideline candidates that should be plain instructions
    # ------------------------------------------------------------------ #
    # A guideline earns the extra classifier LLM call only when it needs to:
    #   (a) conditionally invoke a specific *tool*, OR
    #   (b) enforce truly event-driven routing that cannot be expressed as
    #       a general behavioral rule.
    # When a guideline has NO tool binding AND its condition is either
    # unconditional ("always", "never", "ensure that…") or describes
    # persona / tone / style, the classifier call is pure waste — the
    # action text can live in instructions at zero additional LLM cost.
    instruction_candidates = []

    for g in guidelines:
        if not isinstance(g, dict):
            continue
        name = g.get("display_name") or g.get("id") or "<unnamed>"
        condition = g.get("condition", "").lower().strip()
        has_tool = bool(g.get("tool", "").strip())

        # Skip if it invokes a tool — the classifier is justified there
        if has_tool:
            continue

        reason = None

        # Unconditional pattern: condition fires on every user turn
        if any(tok in condition for tok in _UNCONDITIONAL_TOKENS):
            reason = "condition is unconditional ('always / never / ensure / make sure…') — it fires on every user turn"

        # Persona / tone / style: pure behavioral default, never needs routing
        elif any(tok in condition for tok in _PERSONA_STYLE_TOKENS):
            reason = "condition describes persona, tone, or style — a behavioral default that does not need LLM-based routing"

        # Very short condition with no discriminating keywords: likely a
        # catch-all rule dressed as a guideline (< 8 words, no tool)
        elif len(condition.split()) < 8:
            reason = "condition is very short and non-discriminating — likely a catch-all rule that belongs in instructions"

        if reason:
            instruction_candidates.append((name, reason))

    if instruction_candidates:
        details = "; ".join(f"'{n}' ({r})" for n, r in instruction_candidates)
        findings.append({
            "category": "Guidelines",
            "severity": "medium",
            "anti_pattern": "Instruction-Suitable Guideline",
            "issue": (
                f"{len(instruction_candidates)} guideline(s) have no tool binding and a condition "
                f"that does not require LLM-based routing: {details}. "
                "In watsonx Orchestrate every guideline triggers a classifier LLM call before the "
                "agent loop — this adds latency on every invocation even when the condition is "
                "a blanket rule or style preference that applies universally."
            ),
            "recommendation": (
                "Move these guidelines into the agent's 'instructions' block. Instructions are "
                "compiled into the system prompt once and cost nothing extra per turn. "
                "Reserve guidelines only for (1) conditions that invoke a specific *tool*, or "
                "(2) event-driven routing rules that genuinely need per-turn LLM classification. "
                "Example migration:\n"
                "  BEFORE (guideline):\n"
                "    condition: 'Always respond politely'\n"
                "    action: 'Use a friendly, professional tone in every reply.'\n"
                "  AFTER (instruction line):\n"
                "    'Always use a friendly, professional tone in every reply.'"
            ),
            "reference": (
                "WxO Performance Guide: 'Guidelines trigger an LLM call before the agent loop "
                "starts — use guidelines only when needed, remove if not providing value.' "
                "(developer.watson-orchestrate.ibm.com/tutorials/performance/performance-guide-v2-agent)"
            )
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
