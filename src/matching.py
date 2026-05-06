"""Match employees to tasks via a weighted score with explainable factors.

The function is intentionally simple, additive, and tunable: every weight and
sub-score appears in the output, so the LLM (or a human reviewer) can explain
exactly *why* a recommendation was made.
"""
from __future__ import annotations
from .models import WorldState, Task, Employee, GRADE_LEVEL, Grade
from .analytics import employee_workload_window, past_performance


# Weights — all explicit. Tunable; consider learning these from history later.
W_ROLE         = 0.40
W_GRADE        = 0.20
W_SKILLS       = 0.15
W_AVAILABILITY = 0.15
W_EXPERIENCE   = 0.05
W_MARGIN       = 0.05


def _grade_fit(emp_grade: Grade, req_min: Grade) -> float:
    """1.0 when grade exactly matches; drops if higher (overshoot wastes margin),
    0.0 if under-qualified."""
    delta = GRADE_LEVEL[emp_grade] - GRADE_LEVEL[req_min]
    if delta < 0:
        return 0.0
    return max(0.0, 1.0 - 0.25 * delta)


def _skill_overlap(emp: Employee, task: Task) -> float:
    if not task.tags:
        return 0.5  # no tags → neutral
    overlap = len(set(emp.skills) & set(task.tags))
    return min(1.0, overlap / max(1, len(task.tags)))


def _availability_score(state: WorldState, emp: Employee, task: Task) -> float:
    """Fraction of the task's remaining hours that fits in the employee's free
    capacity between today and the task's deadline. Time off / holidays are
    already baked into employee_workload_window via employee_capacity_hours."""
    days_to_deadline = (task.deadline - state.today).days
    if days_to_deadline <= 0:
        return 0.0
    wl = employee_workload_window(state, emp, days_to_deadline)
    if wl["capacity_hours"] <= 0:
        return 0.0  # full time off in this window
    free, needed = wl["free_hours"], task.remaining_hours
    if needed <= 0:
        return 1.0
    return max(0.0, min(1.0, free / needed))


def _margin_fit(state: WorldState, emp: Employee, task: Task) -> float:
    """Reward when (client_rate - emp.cost) / client_rate ≥ project's target margin."""
    proj = next(p for p in state.projects if p.id == task.project_id)
    rate = proj.client_rate(emp.grade)
    if rate <= 0 or proj.target_margin <= 0:
        return 0.5
    margin = (rate - emp.cost_per_hour) / rate
    return max(0.0, min(1.0, margin / proj.target_margin))


def _experience_score(perf: dict) -> float:
    """speed_ratio = spent/estimate. <1 is fast. Map 1.0→0.5, 0.8→0.7, 1.2→0.3."""
    if perf["completed_tasks"] == 0:
        return 0.5
    return max(0.0, min(1.0, 1.5 - perf["speed_ratio"]))


def _rationale(emp, task, role, grade, skill, avail, margin) -> str:
    parts = []
    if role == 0:
        parts.append(f"роль не совпадает ({emp.role.value} vs {task.required_role.value})")
    if grade == 0:
        parts.append(f"грейд ниже требуемого ({emp.grade.value} < {task.required_grade_min.value})")
    elif grade < 0.6:
        parts.append("грейд выше требуемого — риск переплаты")
    if avail < 0.5:
        parts.append("ограниченная доступность до дедлайна")
    if skill > 0.7:
        parts.append("совпадают навыки задачи")
    if margin < 0.5:
        parts.append("ставка плохо ложится в маржу проекта")
    return "; ".join(parts) or "хорошее совпадение по всем факторам"


def score_match(state: WorldState, employee: Employee, task: Task) -> dict:
    role_match = 1.0 if employee.role == task.required_role else 0.0
    grade_fit  = _grade_fit(employee.grade, task.required_grade_min)
    skill      = _skill_overlap(employee, task)
    avail      = _availability_score(state, employee, task)
    perf       = past_performance(state, employee.id)
    exp_score  = _experience_score(perf)
    margin_fit = _margin_fit(state, employee, task)

    score = (
        W_ROLE         * role_match +
        W_GRADE        * grade_fit  +
        W_SKILLS       * skill      +
        W_AVAILABILITY * avail      +
        W_EXPERIENCE   * exp_score  +
        W_MARGIN       * margin_fit
    )
    return {
        "employee_id": employee.id,
        "employee_name": employee.name,
        "task_id": task.id,
        "task_title": task.title,
        "score": round(score, 3),
        "breakdown": {
            "role_match":       role_match,
            "grade_fit":        round(grade_fit, 2),
            "skill_overlap":    round(skill, 2),
            "availability":     round(avail, 2),
            "past_performance": round(exp_score, 2),
            "margin_fit":       round(margin_fit, 2),
        },
        "rationale": _rationale(employee, task, role_match, grade_fit, skill, avail, margin_fit),
    }


def find_best_assignees(state: WorldState, task: Task, top_k: int = 3) -> list[dict]:
    """Hard-filter on role + min grade, then rank by score."""
    candidates = []
    for emp in state.employees:
        if emp.role != task.required_role:
            continue
        if GRADE_LEVEL[emp.grade] < GRADE_LEVEL[task.required_grade_min]:
            continue
        candidates.append(score_match(state, emp, task))
    candidates.sort(key=lambda x: -x["score"])
    return candidates[:top_k]
