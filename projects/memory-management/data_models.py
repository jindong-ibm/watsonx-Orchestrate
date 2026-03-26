from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import copy
import uuid

@dataclass
class MemoryRecord:
    id: str                     # UUID
    content: Any                # Can include type and payload, etc. Product impl need a structure.

    # metadata
    agent_id: str
    sessionId: Optional[str]
    task_id: Optional[str]
    source: str                 # human | agent | tool | external
    confidence: float
    created_at: float
    
    # semantics, also define importance, decayPolicy, etc. if need
    intent: Optional[str]
    
    # scope
    scope: str                  # for windowing: short (prompt context, turn) | task | session | long
    visibility: str             # for multi-agent memory sharing: private | task | session | global

@dataclass
class ToolExecutionRecord:
    tool_name: str
    tool_input_hash: str
    result: any
    executed_at: float
