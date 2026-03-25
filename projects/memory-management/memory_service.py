

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

    # ------------------------------
    # WRITE PATH
    # ------------------------------

    def write(
        self,
        agent_id: str,
        content: Any,
        scope: str,
        source: str,
        task_id: Optional[str] = None,
        intent: Optional[str] = None,
        confidence: float = 1.0
    ):
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            content=content,
            scope=scope,
            agent_id=agent_id,
            task_id=task_id,
            source=source,
            intent=intent,
            confidence=confidence,
            created_at=time.time()
        )
        self.memory[scope].append(record)

    # ------------------------------
    # READ PATH (Intent + Scope aware)
    # ------------------------------

    def read(
        self,
        agent_id: str,
        scope: str,
        intent: Optional[str] = None,
        max_items: int = 5
    ) -> List[MemoryRecord]:

        records = [
            r for r in self.memory[scope]
            if r.agent_id == agent_id
            and (intent is None or r.intent == intent)
        ]

        # Sort by importance proxy: confidence + recency
        records.sort(
            key=lambda r: (r.confidence, r.created_at),
            reverse=True
        )

        return records[:max_items]

    # ------------------------------
    # DECAY / WATERMARK LOGIC
    # ------------------------------

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

    # ------------------------------
    # TASK COMPLETION CLEANUP
    # ------------------------------

    def clear_task_scope(self, task_id: str):
        self.memory["task"] = [
            r for r in self.memory["task"]
            if r.task_id != task_id
        ]

    # ------------------------------
    # CHECKPOINT / ROLLBACK
    # ------------------------------

    def checkpoint(self):
        snapshot = copy.deepcopy(self.memory)
        self.checkpoints.append(snapshot)

    def rollback(self):
        if not self.checkpoints:
            raise RuntimeError("No checkpoint available")
        self.memory = self.checkpoints.pop()

    # ------------------------------
    # OBSERVABILITY (Simplified)
    # ------------------------------

    def stats(self) -> Dict[str, int]:
        return {
            scope: len(self.memory[scope])
            for scope in self.memory
        }
