"""Analytics primitives — pure functions over WorldState.

These power both the Discord report and the LLM agent's tools. Keeping the
math here (not in the LLM) means numbers in the report are deterministic and
reviewable; the LLM only frames them.
"""
from __future__ import annotations
from datetime import date, timedelta
from collections import defaultdict
from .models import WorldState, Employee, TaskStatus, Grade, GRADE_LEVEL


# ----- time / capacity ------------------------------------------------------

def working_days_between(start: date, end: date,
                          holidays: set[date] | None = None) -> int:
    """Mon-Fri days in [start, end), excluding holidays."""
    holidays = holidays or set()
    days = 0
    d = start
    while d < end:
        if d.weekday() < 5 and d not in holidays:
            days += 1
        d += timedelta(days=1)
    return max(0, days)


def _employee_timeoff_days(state: WorldState, emp: Employee,
                            start: date, end: date) -> int:
    """Working days the employee is on time off (vacation/sick) within [start, end)."""
    holidays = {h.date for h in state.holidays}
    days_off = 0
    for to in state.timeoffs:
        if to.employee_id != emp.id:
            continue
        # Intersect [to.start_date, to.end_date] (inclusive) with [start, end)
        lo = max(to.start_date, start)
        hi = min(to.end_date + timedelta(days=1), end)  # convert inclusive→exclusive
        if lo >= hi:
            continue
        days_off += working_days_between(lo, hi, holidays)
    return days_off


def employee_capacity_hours(state: WorldState, emp: Employee,
                              start: date, end: date) -> float:
    """Working days × daily capacity, minus holidays and time off."""
    holidays = {h.date for h in state.holidays}
    wd = working_days_between(start, end, holidays)
    days_off = _employee_timeoff_days(state, emp, start, end)
    effective_days = max(0, wd - days_off)
    return effective_days * (emp.weekly_capacity_hours / 5.0)


# ----- workload windows -----------------------------------------------------

def employee_workload_window(state: WorldState, emp: Employee,
                              days: int = 14) -> dict:
    """Capacity vs committed hours for `emp` over the next `days` calendar days.

    Capacity = working days in window minus holidays & time off, × daily rate.
    Committed = sum of hours allocated to this employee, with tasks whose
    deadline lies past the window pro-rated linearly over working days.
    """
    today = state.today
    end = today + timedelta(days=days)
    capacity = employee_capacity_hours(state, emp, today, end)
    holidays = {h.date for h in state.holidays}
    wd_window = working_days_between(today, end, holidays)
    committed = 0.0
    for task in state.tasks:
        if task.status == TaskStatus.DONE:
            continue
        # Find this employee's allocation on the task (if any).
        allocs = task.effective_allocations()
        emp_hours = sum(a.hours for a in allocs if a.employee_id == emp.id)
        if emp_hours <= 0:
            continue
        if task.deadline <= today:
            committed += emp_hours
        elif task.deadline <= end:
            committed += emp_hours
        else:
            wd_total = max(1, working_days_between(today, task.deadline, holidays))
            committed += emp_hours * (wd_window / wd_total)
    util = committed / capacity if capacity > 0 else 0.0
    return {
        "employee_id": emp.id,
        "employee_name": emp.name,
        "role": emp.role.value,
        "grade": emp.grade.value,
        "window_days": days,
        "capacity_hours": round(capacity, 1),
        "committed_hours": round(committed, 1),
        "utilization": round(util, 2),
        "free_hours": round(max(0.0, capacity - committed), 1),
    }


def bench_risk(state: WorldState, days: int = 14, threshold: float = 0.5) -> list[dict]:
    """Employees expected to run low on work in the next `days` days."""
    out = []
    for emp in state.employees:
        wl = employee_workload_window(state, emp, days)
        if wl["utilization"] < threshold:
            out.append(wl)
    out.sort(key=lambda x: x["utilization"])
    return out


def overloaded(state: WorldState, days: int = 14, threshold: float = 1.0) -> list[dict]:
    """Employees over capacity, with a list of at-risk tasks attached."""
    out = []
    end = state.today + timedelta(days=days)
    for emp in state.employees:
        wl = employee_workload_window(state, emp, days)
        if wl["utilization"] > threshold:
            at_risk = []
            for task in state.tasks:
                if task.status == TaskStatus.DONE:
                    continue
                allocs = task.effective_allocations()
                if not any(a.employee_id == emp.id for a in allocs):
                    continue
                if task.deadline <= end:
                    emp_hours = sum(a.hours for a in allocs if a.employee_id == emp.id)
                    at_risk.append({
                        "task_id": task.id,
                        "title": task.title,
                        "project_id": task.project_id,
                        "deadline": task.deadline.isoformat(),
                        "remaining_hours": emp_hours,
                    })
            wl["at_risk_tasks"] = at_risk
            out.append(wl)
    out.sort(key=lambda x: -x["utilization"])
    return out


# ----- time-off / upcoming absence ----------------------------------------

def upcoming_time_off(state: WorldState, days: int = 14) -> list[dict]:
    """Time off starting (or ongoing) in the next `days` days."""
    today = state.today
    end = today + timedelta(days=days)
    out = []
    for to in state.timeoffs:
        if to.end_date < today or to.start_date >= end:
            continue
        emp = next((e for e in state.employees if e.id == to.employee_id), None)
        if emp is None:
            continue
        out.append({
            "employee_id": emp.id,
            "employee_name": emp.name,
            "role": emp.role.value,
            "type": to.type,
            "start_date": to.start_date.isoformat(),
            "end_date": to.end_date.isoformat(),
            "days": (to.end_date - to.start_date).days + 1,
        })
    out.sort(key=lambda x: x["start_date"])
    return out


# ----- project economics ---------------------------------------------------

def project_margin_actual(state: WorldState, project_id: str,
                            lookback_days: int = 30) -> dict:
    """Compute actual cost / revenue / margin from time logs in last `lookback_days`."""
    proj = next(p for p in state.projects if p.id == project_id)
    cutoff = state.today - timedelta(days=lookback_days)
    cost = 0.0
    revenue = 0.0
    by_grade_hours: dict[str, float] = defaultdict(float)
    for log in state.timelogs:
        if log.project_id != project_id or log.date < cutoff:
            continue
        emp = next(e for e in state.employees if e.id == log.employee_id)
        cost += emp.cost_per_hour * log.hours
        revenue += proj.client_rate(emp.grade) * log.hours
        by_grade_hours[emp.grade.value] += log.hours
    margin = (revenue - cost) / revenue if revenue > 0 else 0.0
    return {
        "project_id": project_id,
        "project_name": proj.name,
        "lookback_days": lookback_days,
        "cost": round(cost, 2),
        "revenue": round(revenue, 2),
        "margin_actual": round(margin, 3),
        "margin_target": proj.target_margin,
        "delta_vs_target": round(margin - proj.target_margin, 3),
        "hours_by_grade": {k: round(v, 1) for k, v in by_grade_hours.items()},
    }


# ----- inefficiencies ------------------------------------------------------

def grade_mismatches(state: WorldState, gap: int = 2) -> list[dict]:
    """Senior+ doing junior work — wasted margin. `gap` is grade levels above min."""
    out = []
    for task in state.tasks:
        if task.status == TaskStatus.DONE:
            continue
        for alloc in task.effective_allocations():
            emp = next((e for e in state.employees if e.id == alloc.employee_id), None)
            if emp is None:
                continue
            if GRADE_LEVEL[emp.grade] - GRADE_LEVEL[task.required_grade_min] >= gap:
                out.append({
                    "task_id": task.id,
                    "task_title": task.title,
                    "project_id": task.project_id,
                    "employee": emp.name,
                    "employee_grade": emp.grade.value,
                    "required_min_grade": task.required_grade_min.value,
                    "remaining_hours": alloc.hours,
                })
    return out


def expensive_on_low_margin(state: WorldState, lookback_days: int = 14,
                              margin_threshold: float = 0.20) -> list[dict]:
    """Senior+ employees logged on projects whose target margin is below threshold."""
    out = []
    by_emp_proj: dict[tuple[str, str], float] = defaultdict(float)
    cutoff = state.today - timedelta(days=lookback_days)
    for log in state.timelogs:
        if log.date >= cutoff:
            by_emp_proj[(log.employee_id, log.project_id)] += log.hours
    for (eid, pid), hours in by_emp_proj.items():
        if hours < 4:
            continue
        emp = next(e for e in state.employees if e.id == eid)
        proj = next(p for p in state.projects if p.id == pid)
        if (GRADE_LEVEL[emp.grade] >= GRADE_LEVEL[Grade.SENIOR]
                and proj.target_margin < margin_threshold):
            out.append({
                "employee": emp.name,
                "grade": emp.grade.value,
                "cost_per_hour": emp.cost_per_hour,
                "project": proj.name,
                "project_target_margin": proj.target_margin,
                "hours_last_n_days": round(hours, 1),
                "lookback_days": lookback_days,
            })
    return out


def past_performance(state: WorldState, employee_id: str) -> dict:
    """Employee's past-task speed: actual/estimate ratio. <1.0 = faster than estimate."""
    ratios = []
    by_role_hours: dict[str, float] = defaultdict(float)
    for task in state.tasks:
        if task.status != TaskStatus.DONE:
            continue
        # Historical tasks use the legacy single-assignee field
        if task.assignee_id != employee_id:
            continue
        if task.estimate_hours <= 0:
            continue
        ratios.append(task.spent_hours / task.estimate_hours)
        by_role_hours[task.required_role.value] += task.spent_hours
    if not ratios:
        return {"completed_tasks": 0, "speed_ratio": 1.0, "hours_by_role": {}}
    return {
        "completed_tasks": len(ratios),
        "speed_ratio": round(sum(ratios) / len(ratios), 2),
        "hours_by_role": {k: round(v, 1) for k, v in by_role_hours.items()},
    }


def partially_allocated_tasks(state: WorldState) -> list[dict]:
    """Tasks where allocations leave some hours unfilled (need more people)."""
    out = []
    for task in state.tasks:
        if task.status == TaskStatus.DONE:
            continue
        if not task.allocations:
            continue
        if task.unallocated_hours > 0:
            proj = next(p for p in state.projects if p.id == task.project_id)
            out.append({
                "task_id": task.id,
                "task_title": task.title,
                "project_name": proj.name,
                "deadline": task.deadline.isoformat(),
                "required_role": task.required_role.value,
                "required_grade_min": task.required_grade_min.value,
                "total_remaining_hours": task.remaining_hours,
                "allocated_hours": sum(a.hours for a in task.allocations),
                "unallocated_hours": task.unallocated_hours,
                "allocated_to": [
                    next(e.name for e in state.employees if e.id == a.employee_id)
                    for a in task.allocations
                ],
            })
    return out
