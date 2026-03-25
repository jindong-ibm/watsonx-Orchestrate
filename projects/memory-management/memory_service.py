
import hashlib
import uuid
import time
import copy

class MemoryService:
    """
    Control-plane-managed memory service for agent orchestration.
    """

    def __init__(self):
        self.memory: Dict[str, List[MemoryRecord]] = {
            "short": [],
            "task": [],
            "session": [],
            "long": []
        }
        self.checkpoints = []
        self.tool_executions = {}

    def write(
        self,
        agent_id: str,
        content,
        scope: str,
        visibility: str,
        source: str,
        task_id: str | None = None,
        intent: str | None = None,
        confidence: float = 1.0
    ):
        
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=content,
            scope=scope,
            visibility=visibility,
            agent_id=agent_id,
            task_id=task_id,
            source=source,
            intent=intent,
            confidence=confidence,
            created_at=time.time()
        )
        self.memory[scope].append(record)

    def read(
        self,
        agent_id: str,
        scope: str,
        task_id: Optional[str] = None,
        intent: Optional[str] = None,
        max_items: int = 5
    ) -> List[MemoryRecord]:

        records = []
        
        for r in self.memory[scope]:
            if (intent is None or r.intent == intent):
                if r.visibility == "global":
                    records.append(r)
                elif r.visibility == "session" and r.agent_id == agent_id:
                    records.append(r)
                elif r.visibility == "task" and r.task_id == task_id:
                    records.append(r)
                elif r.visibility == "private" and r.agent_id == agent_id:
                    records.append(r)

        # Sort by importance proxy: confidence + recency
        records.sort(
            key=lambda r: (r.confidence, r.created_at),
            reverse=True
        )

        return records[:max_items]

    def execute_tool_exactly_once(self, tool_name, tool_input, tool_fn):
        """
        tool_fn is a callable that executes the real tool.
        """

        input_hash = hashlib.sha256(
            str(tool_input).encode()
        ).hexdigest()

        key = f"{tool_name}:{input_hash}"

        if key in self.tool_executions:
            return self.tool_executions[key].result

        # Execute tool
        result = tool_fn(tool_input)

        self.tool_executions[key] = ToolExecutionRecord(
            tool_name=tool_name,
            tool_input_hash=input_hash,
            result=result,
            executed_at=time.time()
        )

        return result
    
    def decay(self, rate: float = 0.1):
        """
        Apply semantic decay globally.
        Equivalent to watermark-based eviction.
        """
        for scope in self.memory:
            retained = []
            for r in self.memory[scope]:
                r.confidence -= rate
                if r.confidence > 0:
                    retained.append(r)
            self.memory[scope] = retained

    def clear_task_scope(self, task_id: str):
        self.memory["task"] = [
            r for r in self.memory["task"]
            if r.task_id != task_id
        ]

    def checkpoint(self):
        snapshot = copy.deepcopy(self.memory)
        self.checkpoints.append(snapshot)

    def rollback(self):
        if not self.checkpoints:
            raise RuntimeError("No checkpoint available")
        self.memory = self.checkpoints.pop()

    def stats(self) -> Dict[str, int]:
        return {
            scope: len(self.memory[scope])
            for scope in self.memory
        }
