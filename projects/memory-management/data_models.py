from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import copy
import uuid

@dataclass
class MemoryRecord:
    id: str
    content: Any
    scope: str              # short | task | session | long
    agent_id: str
    task_id: Optional[str]
    source: str             # human | agent | tool | external
    intent: Optional[str]
    confidence: float
    created_at: float
