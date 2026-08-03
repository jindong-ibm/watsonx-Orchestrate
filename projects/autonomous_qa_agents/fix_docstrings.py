#!/usr/bin/env python3
"""
Script to fix Google-style docstrings in all tool files.
Adds type hints in parentheses after parameter names in Args sections.
"""

import re
import sys
from pathlib import Path


def fix_docstring(content: str) -> str:
    """
    Fix docstring format to match Google-style with type hints.
    
    Converts:
        Args:
            param_name: Description
    To:
        Args:
            param_name (str): Description
    """
    lines = content.split('\n')
    fixed_lines = []
    in_args_section = False
    
    for i, line in enumerate(lines):
        # Check if we're entering Args section
        if re.match(r'^\s*Args:\s*$', line):
            in_args_section = True
            fixed_lines.append(line)
            continue
        
        # Check if we're leaving Args section
        if in_args_section and re.match(r'^\s*(Returns|Raises|Yields|Examples?):\s*$', line):
            in_args_section = False
            fixed_lines.append(line)
            continue
        
        # Fix parameter lines in Args section
        if in_args_section:
            # Match lines like: "        param_name: Description"
            # But NOT lines that already have type hints like: "        param_name (str): Description"
            match = re.match(r'^(\s+)(\w+):\s+(.+)$', line)
            if match and '(' not in line:
                indent, param_name, description = match.groups()
                
                # Determine type from function signature
                # Look backwards to find the function definition
                func_line_idx = i
                while func_line_idx > 0:
                    if 'def ' in lines[func_line_idx]:
                        break
                    func_line_idx -= 1
                
                # Extract parameter type from function signature
                param_type = 'str'  # default
                for j in range(func_line_idx, min(func_line_idx + 10, len(lines))):
                    if f'{param_name}:' in lines[j]:
                        # Try to extract type hint
                        type_match = re.search(rf'{param_name}:\s*(\w+)', lines[j])
                        if type_match:
                            param_type = type_match.group(1)
                        break
                
                # Reconstruct line with type hint
                fixed_line = f'{indent}{param_name} ({param_type}): {description}'
                fixed_lines.append(fixed_line)
                continue
        
        fixed_lines.append(line)
    
    return '\n'.join(fixed_lines)


def process_file(file_path: Path) -> bool:
    """Process a single Python file to fix docstrings."""
    try:
        content = file_path.read_text()
        fixed_content = fix_docstring(content)
        
        if content != fixed_content:
            file_path.write_text(fixed_content)
            print(f"✓ Fixed: {file_path}")
            return True
        else:
            print(f"  Skipped (no changes needed): {file_path}")
            return False
    except Exception as e:
        print(f"✗ Error processing {file_path}: {e}")
        return False


def main():
    """Main function to process all tool files."""
    tools_dir = Path('tools')
    
    if not tools_dir.exists():
        print("Error: tools directory not found")
        sys.exit(1)
    
    # Find all Python files except __init__.py
    tool_files = [
        f for f in tools_dir.rglob('*.py')
        if f.name != '__init__.py'
    ]
    
    print(f"Found {len(tool_files)} tool files to process\n")
    
    fixed_count = 0
    for tool_file in sorted(tool_files):
        if process_file(tool_file):
            fixed_count += 1
    
    print(f"\n{'='*60}")
    print(f"Summary: Fixed {fixed_count} out of {len(tool_files)} files")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()

# Made with Bob
