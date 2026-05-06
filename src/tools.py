"""Tool wrappers for the LLM agent.

`make_tools(state)` returns:
  - tool_specs:    Anthropic tool-use definitions (JSON schema)
  - tool_handlers: dict mapping tool_name → callable

The LLM never touches WorldState directly; it must go through these tools.
That makes the surface auditable and lets us swap the data source freely.
"""
from __future__ import annotations
from .models import WorldState, TaskStatus
from .analytics import (
    bench_risk, overloaded, project_margin_actual,
    grade_mismatches, expensive_on_low_margin,
    employee_workload_window, upcoming_time_off, partially_allocated_tasks,
)
from .matching import find_best_assignees


def make_tools(state: WorldState):
    def list_unassigned_tasks() -> list[dict]:
        return [
            {
                "task_id": t.id,
                "title": t.title,
                "project_id": t.project_id,
                "required_role": t.required_role.value,
                "required_grade_min": t.required_grade_min.value,
                "estimate_hours": t.estimate_hours,
                "deadline": t.deadline.isoformat(),
                "tags": t.tags,
            }
            for t in state.tasks
            if t.is_unassigned and t.status != TaskStatus.DONE
        ]

    def find_assignees(task_id: str, top_k: int = 3) -> list[dict]:
        task = next((t for t in state.tasks if t.id == task_id), None)
        if task is None:
            return []
        return find_best_assignees(state, task, top_k)

    def get_bench_risk(days: int = 14, threshold: float = 0.5) -> list[dict]:
        return bench_risk(state, days, threshold)

    def get_overloaded(days: int = 14) -> list[dict]:
        return overloaded(state, days)

    def get_all_project_margins() -> list[dict]:
        return [project_margin_actual(state, p.id) for p in state.projects]

    def get_grade_mismatches() -> list[dict]:
        return grade_mismatches(state)

    def get_expensive_on_low_margin() -> list[dict]:
        return expensive_on_low_margin(state)

    def get_employee_workload(employee_id: str, days: int = 14) -> dict:
        emp = next((e for e in state.employees if e.id == employee_id), None)
        if emp is None:
            return {}
        return employee_workload_window(state, emp, days)

    def get_upcoming_time_off(days: int = 14) -> list[dict]:
        return upcoming_time_off(state, days)

    def get_partially_allocated_tasks() -> list[dict]:
        return partially_allocated_tasks(state)

    handlers = {
        "list_unassigned_tasks":          list_unassigned_tasks,
        "find_assignees":                 find_assignees,
        "get_bench_risk":                 get_bench_risk,
        "get_overloaded":                 get_overloaded,
        "get_all_project_margins":        get_all_project_margins,
        "get_grade_mismatches":           get_grade_mismatches,
        "get_expensive_on_low_margin":    get_expensive_on_low_margin,
        "get_employee_workload":          get_employee_workload,
        "get_upcoming_time_off":          get_upcoming_time_off,
        "get_partially_allocated_tasks":  get_partially_allocated_tasks,
    }

    specs = [
        {
            "name": "list_unassigned_tasks",
            "description": "Return all tasks that have no assignee and are not done.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "find_assignees",
            "description": ("Top-k ranked candidates for a task, with per-factor "
                            "score breakdown (role, grade, skills, availability, "
                            "experience, margin) and a short rationale."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "top_k":   {"type": "integer", "default": 3},
                },
                "required": ["task_id"],
            },
        },
        {
            "name": "get_bench_risk",
            "description": "Employees whose committed hours / capacity is below threshold over the next N days.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "days":      {"type": "integer", "default": 14},
                    "threshold": {"type": "number",  "default": 0.5},
                },
                "required": [],
            },
        },
        {
            "name": "get_overloaded",
            "description": "Employees over capacity in the next N days, with at-risk tasks.",
            "input_schema": {
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 14}},
                "required": [],
            },
        },
        {
            "name": "get_all_project_margins",
            "description": "Actual cost / revenue / margin per project from time logs (last 30 days).",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_grade_mismatches",
            "description": "Tasks where assignee grade is ≥2 levels above task's minimum required grade.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_expensive_on_low_margin",
            "description": "Senior+ employees logging hours on projects with low target margin.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_employee_workload",
            "description": "Workload metrics (capacity / committed / utilization) for one employee.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "employee_id": {"type": "string"},
                    "days":        {"type": "integer", "default": 14},
                },
                "required": ["employee_id"],
            },
        },
        {
            "name": "get_upcoming_time_off",
            "description": "Vacations / sick leave / days off starting (or ongoing) in the next N days.",
            "input_schema": {
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 14}},
                "required": [],
            },
        },
        {
            "name": "get_partially_allocated_tasks",
            "description": ("Tasks that have at least one allocation but still have "
                            "unallocated hours — i.e., need extra hands."),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
    ]
    return specs, handlers
