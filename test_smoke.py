"""Smoke tests — sanity checks on the analytics. Not pytest, just assertions."""
from datetime import date, timedelta
from src.data import generate_world
from src.models import (
    Task, TaskStatus, Role, Grade, Employee, Project, TimeLog, WorldState,
    TimeOff, Holiday, Allocation,
)
from src.analytics import (
    working_days_between, employee_capacity_hours, employee_workload_window,
    bench_risk, overloaded, project_margin_actual, grade_mismatches,
    upcoming_time_off, partially_allocated_tasks,
)
from src.matching import find_best_assignees


def _empty_state(today=date(2026, 5, 5), employees=None, projects=None,
                 tasks=None, timelogs=None, timeoffs=None, holidays=None):
    return WorldState(
        today=today,
        employees=employees or [],
        projects=projects or [],
        tasks=tasks or [],
        timelogs=timelogs or [],
        timeoffs=timeoffs or [],
        holidays=holidays or [],
    )


def test_working_days():
    assert working_days_between(date(2026, 5, 5), date(2026, 5, 19)) == 10
    assert working_days_between(date(2026, 5, 5), date(2026, 5, 5)) == 0
    assert working_days_between(date(2026, 5, 9), date(2026, 5, 16)) == 5
    print("✓ working_days_between OK")


def test_holidays_subtract_from_working_days():
    holidays = {date(2026, 5, 7)}  # Thursday → -1
    assert working_days_between(date(2026, 5, 5), date(2026, 5, 19), holidays) == 9
    holidays = {date(2026, 5, 9)}  # Saturday → no double-count
    assert working_days_between(date(2026, 5, 5), date(2026, 5, 19), holidays) == 10
    print("✓ holidays subtract correctly")


def test_capacity():
    e = Employee(id="x", name="X", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=20)
    state = _empty_state(employees=[e])
    cap = employee_capacity_hours(state, e, date(2026, 5, 5), date(2026, 5, 19))
    assert cap == 80.0, f"expected 80, got {cap}"
    print("✓ employee_capacity_hours OK")


def test_capacity_with_timeoff_and_holiday():
    e = Employee(id="x", name="X", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=20)
    timeoffs = [TimeOff(employee_id="x",
                         start_date=date(2026, 5, 11), end_date=date(2026, 5, 15),
                         type="vacation")]
    holidays = [Holiday(date=date(2026, 5, 7), name="National")]
    state = _empty_state(employees=[e], timeoffs=timeoffs, holidays=holidays)
    cap = employee_capacity_hours(state, e, date(2026, 5, 5), date(2026, 5, 19))
    # 10 workdays - 1 holiday - 5 vacation days = 4 days × 8h = 32h
    assert cap == 32.0, f"expected 32, got {cap}"
    print(f"✓ capacity with timeoff + holiday OK ({cap}h)")


def test_overload_detection():
    today = date(2026, 5, 5)
    e = Employee(id="x", name="X", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=20)
    tk = Task(id="t1", project_id="p1", title="Big task", required_role=Role.UNITY,
              required_grade_min=Grade.MIDDLE, estimate_hours=100,
              deadline=today + timedelta(days=10), assignee_id="x",
              status=TaskStatus.IN_PROGRESS, spent_hours=0)
    p = Project(id="p1", name="P", client_rate_per_hour={Grade.JUNIOR: 30, Grade.MIDDLE: 50, Grade.SENIOR: 70, Grade.LEAD: 90})
    state = _empty_state(today=today, employees=[e], projects=[p], tasks=[tk])
    ov = overloaded(state, days=14)
    assert len(ov) == 1
    assert ov[0]["committed_hours"] == 100.0
    assert ov[0]["utilization"] > 1.0
    print("✓ overload detection OK")


def test_proportional_window():
    today = date(2026, 5, 5)
    e = Employee(id="x", name="X", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=20)
    tk = Task(id="t1", project_id="p1", title="Long", required_role=Role.UNITY,
              required_grade_min=Grade.MIDDLE, estimate_hours=40,
              deadline=today + timedelta(days=28), assignee_id="x",
              status=TaskStatus.IN_PROGRESS, spent_hours=0)
    p = Project(id="p1", name="P", client_rate_per_hour={Grade.JUNIOR: 30, Grade.MIDDLE: 50, Grade.SENIOR: 70, Grade.LEAD: 90})
    state = _empty_state(today=today, employees=[e], projects=[p], tasks=[tk])
    wl = employee_workload_window(state, e, days=14)
    assert 18 <= wl["committed_hours"] <= 22, f"expected ~20h, got {wl['committed_hours']}"
    print(f"✓ proportional window OK (committed={wl['committed_hours']}h of 40h)")


def test_partial_allocations_split_workload():
    """Two employees on one task — each gets only their share in workload."""
    today = date(2026, 5, 5)
    senior = Employee(id="s", name="Senior", role=Role.UNITY, grade=Grade.SENIOR, cost_per_hour=40)
    middle = Employee(id="m", name="Middle", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=25)
    p = Project(id="p1", name="P", client_rate_per_hour={Grade.JUNIOR: 30, Grade.MIDDLE: 50, Grade.SENIOR: 70, Grade.LEAD: 90})
    tk = Task(id="t1", project_id="p1", title="Joint feature", required_role=Role.UNITY,
              required_grade_min=Grade.MIDDLE, estimate_hours=60,
              deadline=today + timedelta(days=10), spent_hours=0,
              status=TaskStatus.IN_PROGRESS,
              allocations=[
                  Allocation(employee_id="s", hours=20),
                  Allocation(employee_id="m", hours=30),
              ])
    state = _empty_state(today=today, employees=[senior, middle], projects=[p], tasks=[tk])
    s_wl = employee_workload_window(state, senior, days=14)
    m_wl = employee_workload_window(state, middle, days=14)
    assert s_wl["committed_hours"] == 20.0
    assert m_wl["committed_hours"] == 30.0
    pa = partially_allocated_tasks(state)
    assert len(pa) == 1
    assert pa[0]["unallocated_hours"] == 10.0
    print("✓ partial allocations split workload + flag unfilled")


def test_timeoff_reduces_availability_in_matching():
    today = date(2026, 5, 5)
    avail = Employee(id="a", name="Avail", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=25)
    vac   = Employee(id="v", name="Vacant", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=25)
    timeoffs = [TimeOff(employee_id="v", start_date=today,
                         end_date=today + timedelta(days=14), type="vacation")]
    p = Project(id="p1", name="P", client_rate_per_hour={Grade.JUNIOR: 30, Grade.MIDDLE: 50, Grade.SENIOR: 70, Grade.LEAD: 90})
    tk = Task(id="t1", project_id="p1", title="X", required_role=Role.UNITY,
              required_grade_min=Grade.MIDDLE, estimate_hours=20,
              deadline=today + timedelta(days=14))
    state = _empty_state(today=today, employees=[avail, vac], projects=[p],
                         tasks=[tk], timeoffs=timeoffs)
    cands = find_best_assignees(state, tk, top_k=2)
    assert cands[0]["employee_id"] == "a"
    assert cands[0]["score"] > cands[1]["score"]
    assert cands[1]["breakdown"]["availability"] == 0.0
    print("✓ timeoff hurts availability in matching")


def test_upcoming_time_off_section():
    today = date(2026, 5, 5)
    e = Employee(id="x", name="X", role=Role.UNITY, grade=Grade.MIDDLE, cost_per_hour=20)
    timeoffs = [
        TimeOff(employee_id="x", start_date=today + timedelta(days=3),
                end_date=today + timedelta(days=10), type="vacation"),
        # too far in the future — shouldn't show
        TimeOff(employee_id="x", start_date=today + timedelta(days=30),
                end_date=today + timedelta(days=35), type="vacation"),
    ]
    state = _empty_state(today=today, employees=[e], timeoffs=timeoffs)
    out = upcoming_time_off(state, days=14)
    assert len(out) == 1
    assert out[0]["days"] == 8
    print("✓ upcoming_time_off filters by window")


def test_matching_filters_role_and_grade():
    state = generate_world()
    task = next(t for t in state.tasks if t.required_role == Role.UNITY
                and t.required_grade_min == Grade.SENIOR and t.is_unassigned)
    cands = find_best_assignees(state, task, top_k=10)
    for c in cands:
        emp = next(e for e in state.employees if e.id == c["employee_id"])
        assert emp.role == Role.UNITY
        assert emp.grade in (Grade.SENIOR, Grade.LEAD)
    print(f"✓ matching filters role & grade ({len(cands)} candidates)")


def test_grade_mismatch_detection():
    today = date(2026, 5, 5)
    senior = Employee(id="s", name="Senior", role=Role.UNITY, grade=Grade.LEAD, cost_per_hour=55)
    tk = Task(id="t1", project_id="p1", title="Trivial UI", required_role=Role.UNITY,
              required_grade_min=Grade.JUNIOR, estimate_hours=8,
              deadline=today + timedelta(days=5), assignee_id="s",
              status=TaskStatus.IN_PROGRESS)
    p = Project(id="p1", name="P", client_rate_per_hour={Grade.JUNIOR: 30, Grade.MIDDLE: 50, Grade.SENIOR: 70, Grade.LEAD: 90})
    state = _empty_state(today=today, employees=[senior], projects=[p], tasks=[tk])
    gm = grade_mismatches(state)
    assert len(gm) == 1
    assert gm[0]["employee_grade"] == "lead"
    print("✓ grade mismatch detection OK")


def test_margin_calculation():
    today = date(2026, 5, 5)
    e = Employee(id="x", name="X", role=Role.BACKEND, grade=Grade.SENIOR, cost_per_hour=60)
    p = Project(id="p1", name="P",
                client_rate_per_hour={Grade.JUNIOR: 30, Grade.MIDDLE: 50, Grade.SENIOR: 100, Grade.LEAD: 120},
                target_margin=0.4)
    log = TimeLog(employee_id="x", task_id="t1", project_id="p1",
                  date=today - timedelta(days=5), hours=10)
    state = _empty_state(today=today, employees=[e], projects=[p], timelogs=[log])
    m = project_margin_actual(state, "p1")
    assert m["margin_actual"] == 0.4
    assert m["delta_vs_target"] == 0.0
    print(f"✓ margin calculation OK (got {m['margin_actual']*100}%)")


def test_end_to_end_report():
    state = generate_world()
    from src.report import build_deterministic_report
    report = build_deterministic_report(state)
    for section in ["Bench risk", "Overload", "Маржа", "нераспределённым",
                     "Свободны", "отпуске"]:
        assert section in report, f"section {section!r} missing"
    print("✓ end-to-end report contains all sections")


if __name__ == "__main__":
    test_working_days()
    test_holidays_subtract_from_working_days()
    test_capacity()
    test_capacity_with_timeoff_and_holiday()
    test_overload_detection()
    test_proportional_window()
    test_partial_allocations_split_workload()
    test_timeoff_reduces_availability_in_matching()
    test_upcoming_time_off_section()
    test_matching_filters_role_and_grade()
    test_grade_mismatch_detection()
    test_margin_calculation()
    test_end_to_end_report()
    print("\nAll smoke tests passed.")
