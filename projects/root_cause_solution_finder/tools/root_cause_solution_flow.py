"""
Flow for finding root cause solutions from IBM documentation.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission
from .search_ibm_docs import search_ibm_docs


class RootCauseInput(BaseModel):
    """Input schema for root cause solution finder flow."""
    issue_keyword: str = Field(
        description="The root cause issue to search for (e.g., 'OutOfMemory', 'CrashLoopBackOff', 'Connection refused')"
    )


class RootCauseOutput(BaseModel):
    """Output schema for root cause solution finder flow."""
    issue: str = Field(description="The searched issue keyword")
    sources_searched: List[str] = Field(description="List of documentation sources searched")
    total_results: int = Field(description="Total number of results found")
    top_solutions: List[Dict[str, Any]] = Field(description="Top ranked solutions")
    summary: str = Field(description="Summary of findings and recommendations")


@tool(permission=ToolPermission.READ_ONLY)
def format_solutions(search_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format and enhance search results with a comprehensive summary.
    
    Args:
        search_results: Raw search results from search_ibm_docs
    
    Returns:
        Formatted results with summary
    """
    issue = search_results.get('issue', 'Unknown')
    solutions = search_results.get('solutions', [])
    sources = search_results.get('sources_searched', [])
    total = search_results.get('total_results', 0)
    
    # Generate summary
    if total == 0:
        summary = f"No solutions found for '{issue}' in IBM documentation. Consider:\n"
        summary += "1. Checking IBM Support forums\n"
        summary += "2. Opening a support ticket\n"
        summary += "3. Reviewing system logs for more context\n"
        summary += "4. Searching with alternative keywords"
    else:
        summary = f"Found {total} potential solutions for '{issue}' across {len(sources)} documentation sources.\n\n"
        summary += "Top recommendations:\n"
        
        for i, solution in enumerate(solutions[:3], 1):
            summary += f"\n{i}. {solution['title']}\n"
            summary += f"   Source: {solution['source']}\n"
            summary += f"   URL: {solution['url']}\n"
            summary += f"   Relevance: {solution['relevance_score']}/10\n"
            summary += f"   Preview: {solution['snippet'][:150]}...\n"
        
        summary += "\n\nTroubleshooting Steps:\n"
        summary += "1. Review the top-ranked solutions above\n"
        summary += "2. Check if your environment matches the documented scenarios\n"
        summary += "3. Follow the recommended fixes step-by-step\n"
        summary += "4. Verify the solution resolves your issue\n"
        summary += "5. If issue persists, try the next highest-ranked solution"
    
    return {
        "issue": issue,
        "sources_searched": sources,
        "total_results": total,
        "top_solutions": solutions,
        "summary": summary
    }


@flow(
    name="root_cause_solution_flow",
    display_name="Root Cause Solution Finder Flow",
    description="Searches IBM documentation for root cause solutions and provides comprehensive troubleshooting guidance",
    input_schema=RootCauseInput,
    output_schema=RootCauseOutput
)
def build_root_cause_solution_flow(aflow: Flow) -> Flow:
    """
    Build the root cause solution finder flow.
    
    This flow:
    1. Takes a root cause issue keyword as input
    2. Searches multiple IBM documentation sources
    3. Ranks and formats the results
    4. Provides comprehensive troubleshooting guidance
    
    Args:
        aflow: Flow builder instance
    
    Returns:
        Configured flow
    """
    # Node 1: Search IBM documentation
    search_node = aflow.tool(
        search_ibm_docs,
        name="search_docs",
        display_name="Search IBM Documentation"
    )
    search_node.map_input(
        input_variable="issue_keyword",
        expression="flow.input.issue_keyword"
    )
    
    # Node 2: Format and enhance results
    format_node = aflow.tool(
        format_solutions,
        name="format_results",
        display_name="Format Solutions"
    )
    format_node.map_input(
        input_variable="search_results",
        expression="flow.search_docs.output"
    )
    
    # Define flow sequence
    aflow.sequence(START, search_node, format_node, END)
    
    # Map outputs
    aflow.map_output(
        output_variable="issue",
        expression="flow.format_results.output.issue"
    )
    aflow.map_output(
        output_variable="sources_searched",
        expression="flow.format_results.output.sources_searched"
    )
    aflow.map_output(
        output_variable="total_results",
        expression="flow.format_results.output.total_results"
    )
    aflow.map_output(
        output_variable="top_solutions",
        expression="flow.format_results.output.top_solutions"
    )
    aflow.map_output(
        output_variable="summary",
        expression="flow.format_results.output.summary"
    )
    
    return aflow

# Made with Bob
