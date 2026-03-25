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
        
def main() -> None:

    memory = MemoryService()

    # Agent Context Window
    memory.write(
        agent_id="agent-1",
        content="User prefers concise answers",
        scope="short",
        source="human",
        intent="preference"
    )

    memory.write(
        agent_id="agent-1",
        content="Explaining memory architecture",
        scope="short",
        source="agent",
        intent="current_task"
    )

    context = memory.read(
        agent_id="agent-1",
        scope="short",
        max_items=3
    )

    for r in context:
        print(r.content)

    # Task‑Scoped Reasoning
    memory.write(
        agent_id="agent-1",
        content="Budget capped at $10k",
        scope="task",
        task_id="task-42",
        source="human",
        intent="constraint"
    )

    memory.write(
        agent_id="agent-1",
        content="Chose vendor A due to compliance",
        scope="task",
        task_id="task-42",
        source="agent",
        intent="decision"
    )

    memory.clear_task_scope(task_id="task-42")

    # Semantic Watermark (Decay)
    memory.decay(rate=0.3)
    print(memory.stats())

    # Checkpoint & Replay
    memory.checkpoint()

    memory.write(
        agent_id="agent-1",
        content="Potential hallucinated fact",
        scope="long",
        source="agent",
        confidence=0.2
    )

    # Roll back after detection
    memory.rollback()

    # Shared Task Memory
    memory.write(
        agent_id="planner",
        content="Use vendor A due to compliance",
        scope="task",
        visibility="task",
        task_id="task-99",
        source="agent",
        intent="plan"
    )
    
    executor_context = memory.read(
        agent_id="executor",
        scope="task",
        task_id="task-99"
    )

    for r in executor_context:
        print(r.content)

    # Exactly‑Once Tool Call During Replay
    def provision_resource(input):
        print("PROVISIONING RESOURCE")
        return {"status": "created"}

    result1 = memory.execute_tool_exactly_once(
        "provision",
        {"size": "large"},
        provision_resource
    )

    result2 = memory.execute_tool_exactly_once(
        "provision",
        {"size": "large"},
        provision_resource
    )

    # "PROVISIONING RESOURCE" printed only once

    memory.checkpoints.append(
        copy.deepcopy((memory.memory, memory.tool_executions))
    )

    # Rollback
    memory.memory, memory.tool_executions = memory.checkpoints.pop()

if __name__ == "__main__":
    main()
