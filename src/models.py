"""Domain models for the Resource Allocation Agent.

These models intentionally stay close to what AppTask / a real time-tracker
would expose, so the production adapters can map straight into them.
"""
from __future__ import annotations
from datetime import date
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field


class Role(str, Enum):
    UNITY = "unity"
    UNREAL = "unreal"
    BACKEND = "backend"
    FRONTEND = "frontend"
    MOBILE = "mobile"
    QA = "qa"
    PM = "pm"
    GAME_DESIGNER = "game_designer"
    ARTIST = "artist"
    DEVOPS = "devops"


class Grade(str, Enum):
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    LEAD = "lead"


GRADE_LEVEL: dict[Grade, int] = {
    Grade.JUNIOR: 1,
    Grade.MIDDLE: 2,
    Grade.SENIOR: 3,
    Grade.LEAD: 4,
}


class Employee(BaseModel):
    id: str
    name: str
    role: Role
    grade: Grade
    cost_per_hour: float          # internal cost (salary + overhead) per hour
    weekly_capacity_hours: float = 40.0
    skills: list[str] = Field(default_factory=list)


class Project(BaseModel):
    id: str
    name: str
    # Client rate per grade (USD/hr). Some clients pay flat; we model the general case.
    client_rate_per_hour: dict[Grade, float]
    target_margin: float = 0.4

    def client_rate(self, grade: Grade) -> float:
        return self.client_rate_per_hour[grade]


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Allocation(BaseModel):
    """An employee committed to a task for a specific number of hours.

    Two people can be allocated to one task with different hour shares
    (e.g. senior leads architecture, junior implements UI). Sum of allocation
    hours should be ≤ task.estimate_hours, but is not enforced — the agent
    flags a `Task.unallocated_hours > 0` situation in the report.
    """
    employee_id: str
    hours: float


class Task(BaseModel):
    id: str
    project_id: str
    title: str
    required_role: Role
    required_grade_min: Grade = Grade.JUNIOR
    estimate_hours: float
    deadline: date
    # Backwards-compat single assignee. If `allocations` is non-empty, it wins.
    assignee_id: Optional[str] = None
    allocations: list[Allocation] = Field(default_factory=list)
    spent_hours: float = 0.0
    status: TaskStatus = TaskStatus.OPEN
    tags: list[str] = Field(default_factory=list)

    @property
    def remaining_hours(self) -> float:
        return max(0.0, self.estimate_hours - self.spent_hours)

    def effective_allocations(self) -> list[Allocation]:
        """Return allocations to use for capacity math.

        Rules:
          - explicit allocations win;
          - else if assignee_id is set, synthesize one allocation at remaining hours;
          - else: empty (task is unassigned).
        """
        if self.allocations:
            return self.allocations
        if self.assignee_id:
            return [Allocation(employee_id=self.assignee_id, hours=self.remaining_hours)]
        return []

    @property
    def unallocated_hours(self) -> float:
        if not self.allocations:
            # No partial allocations → either fully assigned (single assignee) or fully open
            return self.remaining_hours if self.assignee_id is None else 0.0
        return max(0.0, self.remaining_hours - sum(a.hours for a in self.allocations))

    @property
    def is_unassigned(self) -> bool:
        return self.assignee_id is None and not self.allocations


class TimeLog(BaseModel):
    employee_id: str
    task_id: str
    project_id: str
    date: date
    hours: float


class TimeOff(BaseModel):
    """Employee unavailable. Inclusive on both ends."""
    employee_id: str
    start_date: date
    end_date: date
    type: Literal["vacation", "sick", "dayoff"] = "vacation"


class Holiday(BaseModel):
    date: date
    name: str


class WorldState(BaseModel):
    """Snapshot of the company at a point in time. Everything the agent reasons
    about derives from here, so the parsers' job is just to materialize this."""
    today: date
    employees: list[Employee]
    projects: list[Project]
    tasks: list[Task]
    timelogs: list[TimeLog]
    timeoffs: list[TimeOff] = Field(default_factory=list)
    holidays: list[Holiday] = Field(default_factory=list)
