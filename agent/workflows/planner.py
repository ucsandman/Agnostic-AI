"""
agent/workflows/planner.py — Dynamic Workflows & Goal-Driven Execution Planner
Provides deterministic multi-step planning, verification criteria tracking, and step loops (Claude Code pattern).
"""

from typing import List, Dict, Any


class PlanStep:
    def __init__(
        self,
        step_number: int,
        description: str,
        verification: str,
        status: str = "pending",
    ):
        self.step_number = step_number
        self.description = description
        self.verification = verification
        self.status = status  # 'pending', 'in_progress', 'completed', 'failed'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step_number,
            "description": self.description,
            "verification": self.verification,
            "status": self.status,
        }


class ExecutionPlan:  # noqa: vulture
    def __init__(self, objective: str):
        self.objective = objective
        self.steps: List[PlanStep] = []
        self.deviations: List[str] = []

    def add_step(self, description: str, verification: str):
        step_num = len(self.steps) + 1
        self.steps.append(PlanStep(step_num, description, verification))

    def update_status(self, step_number: int, status: str):
        for s in self.steps:
            if s.step_number == step_number:
                s.status = status
                break

    def record_deviation(self, deviation: str):
        self.deviations.append(deviation)

    def render_markdown(self) -> str:
        md = [f"## Plan: {self.objective}\n"]
        for s in self.steps:
            mark = (
                "[x]"
                if s.status == "completed"
                else "[ ]"
                if s.status == "pending"
                else "[-]"
            )
            md.append(
                f"{mark} Step {s.step_number}: {s.description} → verify: {s.verification} ({s.status})"
            )
        if self.deviations:
            md.append("\n### Deviations Log:")
            for d in self.deviations:
                md.append(f"- {d}")
        return "\n".join(md)
