"""
Tool for searching IBM documentation sources for root cause solutions.
"""
from typing import List, Dict, Any
from urllib.parse import urljoin, urlparse
import re
import logging
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@tool(permission=ToolPermission.READ_ONLY)
def search_ibm_docs(issue_keyword: str) -> Dict[str, Any]:
    """
    Search IBM documentation sources for root cause solutions.
    
    This tool searches multiple IBM documentation sources recursively for solutions
    to common issues like OutOfMemory, CrashLoopBackOff, Connection refused, etc.
    
    Args:
        issue_keyword: The root cause issue to search for (e.g., "OutOfMemory", "CrashLoopBackOff")
    
    Returns:
        Dictionary containing:
        - issue: The searched issue keyword
        - sources_searched: List of documentation sources searched
        - solutions: List of solution dictionaries with title, url, snippet, and relevance_score
        - total_results: Total number of results found
    """
    # Import dependencies inside the function to avoid import errors during module loading
    # These will be installed via requirements.txt during tool import
    import requests
    from bs4 import BeautifulSoup
    
    logger.info(f"Searching IBM documentation for issue: {issue_keyword}")
    
    # Documentation sources to search
    doc_sources = [
        {
            "name": "watsonx Orchestrate Developer",
            "base_url": "https://developer.watson-orchestrate.ibm.com/",
            "search_paths": [
                "docs/",
                "api/",
                "troubleshooting/"
            ]
        },
        {
            "name": "watsonx Orchestrate Base Docs",
            "base_url": "https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base",
            "search_paths": [
                "troubleshooting",
                "reference",
                "admin"
            ]
        },
        {
            "name": "Software Hub Docs",
            "base_url": "https://www.ibm.com/docs/en/software-hub/5.3.x",
            "search_paths": [
                "troubleshooting",
                "reference"
            ]
        }
    ]
    
    all_solutions = []
    sources_searched = []
    
    for source in doc_sources:
        sources_searched.append(source["name"])
        logger.info(f"Searching {source['name']}...")
        
        try:
            # Search each path in the source
            for search_path in source["search_paths"]:
                url = urljoin(source["base_url"], search_path)
                solutions = _search_documentation_page(url, issue_keyword, source["name"])
                all_solutions.extend(solutions)
        except Exception as e:
            logger.error(f"Error searching {source['name']}: {str(e)}")
            continue
    
    # Rank solutions by relevance
    ranked_solutions = _rank_solutions(all_solutions, issue_keyword)
    
    return {
        "issue": issue_keyword,
        "sources_searched": sources_searched,
        "solutions": ranked_solutions[:10],  # Return top 10 results
        "total_results": len(ranked_solutions)
    }


def _search_documentation_page(url: str, keyword: str, source_name: str) -> List[Dict[str, Any]]:
    """
    Search a documentation page for relevant content.
    
    Args:
        url: URL to search
        keyword: Keyword to search for
        source_name: Name of the documentation source
    
    Returns:
        List of solution dictionaries
    """
    solutions = []
    
    try:
        # Set headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Search for keyword in page content
        text_content = soup.get_text()
        
        # Find all sections containing the keyword
        keyword_lower = keyword.lower()
        if keyword_lower in text_content.lower():
            # Extract relevant sections
            sections = soup.find_all(['section', 'article', 'div'], class_=re.compile(r'(content|article|section|doc)'))
            
            for section in sections:
                section_text = section.get_text()
                if keyword_lower in section_text.lower():
                    # Extract title
                    title_elem = section.find(['h1', 'h2', 'h3', 'h4'])
                    title = title_elem.get_text().strip() if title_elem else "Solution"
                    
                    # Extract snippet around keyword
                    snippet = _extract_snippet(section_text, keyword, max_length=300)
                    
                    solutions.append({
                        "title": title,
                        "url": url,
                        "source": source_name,
                        "snippet": snippet,
                        "relevance_score": 0  # Will be calculated later
                    })
        
        # Also search for links to related pages
        links = soup.find_all('a', href=True)
        for link in links:
            link_text = link.get_text().lower()
            if keyword_lower in link_text or any(term in link_text for term in ['troubleshoot', 'error', 'issue', 'problem']):
                href = link['href']
                full_url = urljoin(url, href)
                
                # Avoid duplicates and external links
                if full_url not in [s['url'] for s in solutions] and urlparse(full_url).netloc == urlparse(url).netloc:
                    solutions.append({
                        "title": link.get_text().strip(),
                        "url": full_url,
                        "source": source_name,
                        "snippet": f"Related documentation: {link.get_text().strip()}",
                        "relevance_score": 0
                    })
    
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch {url}: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing {url}: {str(e)}")
    
    return solutions


def _extract_snippet(text: str, keyword: str, max_length: int = 300) -> str:
    """
    Extract a snippet of text around the keyword.
    
    Args:
        text: Full text to extract from
        keyword: Keyword to center the snippet around
        max_length: Maximum length of the snippet
    
    Returns:
        Text snippet
    """
    text = ' '.join(text.split())  # Normalize whitespace
    keyword_lower = keyword.lower()
    text_lower = text.lower()
    
    # Find keyword position
    pos = text_lower.find(keyword_lower)
    if pos == -1:
        return text[:max_length] + "..." if len(text) > max_length else text
    
    # Extract context around keyword
    start = max(0, pos - max_length // 2)
    end = min(len(text), pos + max_length // 2)
    
    snippet = text[start:end]
    
    # Add ellipsis if truncated
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    
    return snippet


def _rank_solutions(solutions: List[Dict[str, Any]], keyword: str) -> List[Dict[str, Any]]:
    """
    Rank solutions by relevance to the keyword.
    
    Args:
        solutions: List of solution dictionaries
        keyword: Search keyword
    
    Returns:
        Sorted list of solutions by relevance score (descending)
    """
    keyword_lower = keyword.lower()
    
    for solution in solutions:
        score = 0
        
        # Title match (highest weight)
        if keyword_lower in solution['title'].lower():
            score += 10
        
        # Snippet match
        snippet_lower = solution['snippet'].lower()
        keyword_count = snippet_lower.count(keyword_lower)
        score += keyword_count * 5
        
        # Troubleshooting-related terms
        troubleshoot_terms = ['troubleshoot', 'error', 'fix', 'solution', 'resolve', 'issue', 'problem']
        for term in troubleshoot_terms:
            if term in solution['title'].lower() or term in snippet_lower:
                score += 2
        
        solution['relevance_score'] = score
    
    # Sort by relevance score (descending)
    return sorted(solutions, key=lambda x: x['relevance_score'], reverse=True)

# Made with Bob
