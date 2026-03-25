from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import copy
import uuid

class MemoryRecord:
    id: str
    content: Any
    scope: str                  # short | task | session | long
    visibility: str             # private | task | session | global
    agent_id: str
    task_id: Optional[str]
    source: str                 # human | agent | tool | external
    intent: Optional[str]
    confidence: float
    created_at: float

@dataclass
class ToolExecutionRecord:
    tool_name: str
    tool_input_hash: str
    result: any
    executed_at: float
