"""
Programmatic testing script for Root Cause Solution Finder Flow.

This script demonstrates how to:
1. Build and compile the root cause solution flow
2. Deploy it to the watsonx Orchestrate environment
3. Invoke it with test inputs
4. Save the compiled flow specification

Usage:
    export PYTHONPATH=/path/to/watsonx-orchestrate-adk/src:/path/to/watsonx-orchestrate-adk
    python3 flow_main.py
"""

import asyncio
from pathlib import Path
from root_cause_solution_finder.tools.root_cause_solution_flow import build_root_cause_solution_flow


async def main():
    """
    Main function to test the root cause solution finder flow.
    """
    print("=" * 70)
    print("Root Cause Solution Finder Flow - Programmatic Test")
    print("=" * 70)
    print()
    
    # Build and compile the flow
    print("Building and compiling the flow...")
    flow_def = await build_root_cause_solution_flow().compile_deploy()
    print("✓ Flow compiled successfully")
    print()
    
    # Save the compiled flow specification
    generated_folder = f"{Path(__file__).resolve().parent}/generated"
    Path(generated_folder).mkdir(exist_ok=True)
    flow_spec_path = f"{generated_folder}/root_cause_solution_flow.json"
    flow_def.dump_spec(flow_spec_path)
    print(f"✓ Flow specification saved to: {flow_spec_path}")
    print()
    
    # Test cases
    test_cases = [
        {
            "name": "OutOfMemory Error",
            "input": {"issue_keyword": "OutOfMemory"}
        },
        {
            "name": "CrashLoopBackOff Error",
            "input": {"issue_keyword": "CrashLoopBackOff"}
        },
        {
            "name": "Connection Refused Error",
            "input": {"issue_keyword": "Connection refused"}
        }
    ]
    
    # Run test cases
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test Case {i}: {test_case['name']}")
        print("-" * 70)
        print(f"Input: {test_case['input']}")
        print()
        
        try:
            # Invoke the flow with debug mode enabled
            result = await flow_def.invoke(test_case['input'], debug=True)
            
            print("Output:")
            print(f"  Issue: {result.get('issue', 'N/A')}")
            print(f"  Sources Searched: {', '.join(result.get('sources_searched', []))}")
            print(f"  Total Results: {result.get('total_results', 0)}")
            print()
            
            # Display top solutions
            top_solutions = result.get('top_solutions', [])
            if top_solutions:
                print(f"  Top {min(3, len(top_solutions))} Solutions:")
                for j, solution in enumerate(top_solutions[:3], 1):
                    print(f"    {j}. {solution.get('title', 'N/A')}")
                    print(f"       Source: {solution.get('source', 'N/A')}")
                    print(f"       URL: {solution.get('url', 'N/A')}")
                    print(f"       Relevance: {solution.get('relevance_score', 0)}/10")
                    print()
            else:
                print("  No solutions found")
                print()
            
            # Display summary
            summary = result.get('summary', '')
            if summary:
                print("  Summary:")
                # Print first 300 characters of summary
                summary_preview = summary[:300] + "..." if len(summary) > 300 else summary
                for line in summary_preview.split('\n'):
                    print(f"    {line}")
                print()
            
            print("✓ Test case completed successfully")
            
        except Exception as e:
            print(f"✗ Test case failed with error: {str(e)}")
        
        print()
        print("=" * 70)
        print()
    
    print("All test cases completed!")
    print()
    print("Next steps:")
    print("  1. Review the generated flow specification in the 'generated' folder")
    print("  2. Import the agent using: ./import-all.sh")
    print("  3. Test via chat UI: orchestrate chat start")


if __name__ == "__main__":
    asyncio.run(main())

# Made with Bob
