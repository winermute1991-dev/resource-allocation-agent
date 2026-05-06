"""Synthetic data generator.

In production this file is replaced by adapters:
- `apptask.py`   — pulls Task, TimeLog, Project from AppTask via REST/GraphQL
- `hris.py`      — pulls Employee + cost_per_hour from HRIS / 1C
- `client_rates.py` — pulls per-project client rates from finance sheet

The agent code never reads from these adapters directly; it only sees a
fully populated `WorldState`. That keeps the agent pure and testable.
"""
from __future__ import annotations
import random
from datetime import date, timedelta
from .models import (
    Employee, Project, Task, TimeLog, WorldState,
    Role, Grade, TaskStatus, TimeOff, Holiday, Allocation,
)


def _rate_table(j: float, m: float, s: float, l: float) -> dict[Grade, float]:
    return {Grade.JUNIOR: j, Grade.MIDDLE: m, Grade.SENIOR: s, Grade.LEAD: l}


def generate_world(today: date | None = None, seed: int = 42) -> WorldState:
    rng = random.Random(seed)
    today = today or date.today()

    # ---- Team ----
    employees = [
        Employee(id="e01", name="Антон Лебедев",     role=Role.UNITY,         grade=Grade.LEAD,    cost_per_hour=55, skills=["URP", "Shader Graph", "ECS", "Architecture", "Multiplayer"]),
        Employee(id="e02", name="Борис Иванов",      role=Role.UNITY,         grade=Grade.SENIOR,  cost_per_hour=42, skills=["URP", "Shader Graph", "Multiplayer"]),
        Employee(id="e03", name="Влад Петров",       role=Role.UNITY,         grade=Grade.MIDDLE,  cost_per_hour=28, skills=["UI", "Animation"]),
        Employee(id="e04", name="Галина Орлова",     role=Role.UNITY,         grade=Grade.JUNIOR,  cost_per_hour=15, skills=["UI"]),
        Employee(id="e05", name="Дмитрий Кузнецов",  role=Role.UNREAL,        grade=Grade.SENIOR,  cost_per_hour=45, skills=["Niagara", "Multiplayer", "Blueprints"]),
        Employee(id="e06", name="Егор Смирнов",      role=Role.UNREAL,        grade=Grade.MIDDLE,  cost_per_hour=30, skills=["Blueprints", "AI"]),
        Employee(id="e07", name="Фёдор Семёнов",     role=Role.BACKEND,       grade=Grade.SENIOR,  cost_per_hour=40, skills=["Go", "Postgres", "Microservices"]),
        Employee(id="e08", name="Зоя Морозова",      role=Role.BACKEND,       grade=Grade.MIDDLE,  cost_per_hour=27, skills=["Python", "FastAPI", "Postgres"]),
        Employee(id="e09", name="Иван Ковалёв",      role=Role.FRONTEND,      grade=Grade.MIDDLE,  cost_per_hour=26, skills=["React", "TypeScript", "Tailwind"]),
        Employee(id="e10", name="Константин Волков", role=Role.FRONTEND,      grade=Grade.JUNIOR,  cost_per_hour=14, skills=["React"]),
        Employee(id="e11", name="Лариса Соколова",   role=Role.MOBILE,        grade=Grade.SENIOR,  cost_per_hour=42, skills=["Flutter", "Native iOS", "Native Android"]),
        Employee(id="e12", name="Максим Алексеев",   role=Role.QA,            grade=Grade.MIDDLE,  cost_per_hour=22, skills=["Manual", "Regression", "Mobile"]),
        Employee(id="e13", name="Никита Захаров",    role=Role.DEVOPS,        grade=Grade.SENIOR,  cost_per_hour=43, skills=["K8s", "Terraform", "AWS"]),
        Employee(id="e14", name="Ольга Лебедева",    role=Role.GAME_DESIGNER, grade=Grade.MIDDLE,  cost_per_hour=24, skills=["Game Design", "Balance"]),
    ]

    # ---- Projects (with deliberately varied margin profiles) ----
    projects = [
        Project(id="p1", name="Skyforge Online (Unity MMO)",
                client_rate_per_hour=_rate_table(35, 55, 80, 100), target_margin=0.45),
        Project(id="p2", name="Tactical Strike (Unreal FPS)",
                client_rate_per_hour=_rate_table(35, 55, 80, 100), target_margin=0.40),
        Project(id="p3", name="Internal Dev Tools",            # internal initiative — low/no margin
                client_rate_per_hour=_rate_table(20, 30, 45, 55), target_margin=0.10),
        Project(id="p4", name="MobileQuest (Casual)",
                client_rate_per_hour=_rate_table(30, 50, 70, 90), target_margin=0.35),
        Project(id="p5", name="AdminPanel-Acme",
                client_rate_per_hour=_rate_table(35, 50, 75, 95), target_margin=0.50),
    ]

    # ---- Tasks ----
    tasks: list[Task] = []
    counter = {"n": 0}

    def t(project_id, title, role, grade_min, est, days_ahead,
          assignee=None, tags=None, status=TaskStatus.OPEN, spent=0.0):
        counter["n"] += 1
        return Task(
            id=f"t{counter['n']:03d}",
            project_id=project_id,
            title=title,
            required_role=role,
            required_grade_min=grade_min,
            estimate_hours=est,
            deadline=today + timedelta(days=days_ahead),
            assignee_id=assignee,
            tags=tags or [],
            status=status,
            spent_hours=spent,
        )

    # Skyforge (p1) — Unity-heavy, going strong.
    # Note: combat refactor is shared between Lead (architecture, 24h)
    # and Senior (implementation, 36h) — partial allocations example.
    combat_task = Task(
        id="t001", project_id="p1",
        title="Combat system architecture refactor",
        required_role=Role.UNITY, required_grade_min=Grade.SENIOR,
        estimate_hours=60, deadline=today + timedelta(days=14),
        spent_hours=18, status=TaskStatus.IN_PROGRESS,
        tags=["Architecture"],
        allocations=[
            Allocation(employee_id="e01", hours=18),  # Lead — architecture
            Allocation(employee_id="e02", hours=12),  # Senior — partial; rest unallocated
        ],
    )
    counter["n"] = 1
    tasks.append(combat_task)
    tasks += [
        t("p1", "URP shader for water surface",         Role.UNITY,   Grade.MIDDLE, 24,  7, "e02", ["URP", "Shader Graph"],     TaskStatus.IN_PROGRESS,  6),
        t("p1", "Inventory UI",                         Role.UNITY,   Grade.JUNIOR, 32, 21, "e04", ["UI"],                       TaskStatus.IN_PROGRESS,  8),
        t("p1", "Multiplayer netcode latency fix",      Role.UNITY,   Grade.SENIOR, 16,  5, None, ["Multiplayer"]),
        t("p1", "Boss fight prototype",                 Role.UNITY,   Grade.MIDDLE, 40, 28, None, ["Animation"]),
        t("p1", "Backend matchmaking service",          Role.BACKEND, Grade.SENIOR, 48, 21, "e07", ["Go", "Microservices"],     TaskStatus.IN_PROGRESS, 12),
        t("p1", "Game balance pass",                    Role.GAME_DESIGNER, Grade.MIDDLE, 24, 14, "e14", ["Balance"],            TaskStatus.IN_PROGRESS,  8),
    ]
    # Tactical Strike (p2)
    tasks += [
        t("p2", "Niagara muzzle flash VFX",             Role.UNREAL,  Grade.SENIOR, 16, 10, "e05", ["Niagara"],                 TaskStatus.IN_PROGRESS, 4),
        t("p2", "AI patrol behavior",                   Role.UNREAL,  Grade.MIDDLE, 32, 18, "e06", ["AI", "Blueprints"],        TaskStatus.IN_PROGRESS, 10),
        t("p2", "Weapon recoil tuning",                 Role.UNREAL,  Grade.MIDDLE, 16,  7, None, ["Blueprints"]),
        t("p2", "Server-side hit registration",         Role.UNREAL,  Grade.SENIOR, 40, 21, None, ["Multiplayer"]),
        t("p2", "Regression test pass",                 Role.QA,      Grade.MIDDLE, 24, 12, None, ["Regression"]),
    ]
    # Internal tools (p3) — intentionally low margin to surface "expensive on low margin" finding
    tasks += [
        t("p3", "Internal CRM admin migration",         Role.BACKEND, Grade.MIDDLE, 32, 14, "e08", ["Python", "Postgres"],     TaskStatus.IN_PROGRESS, 12),
        t("p3", "Deploy pipeline cleanup",              Role.DEVOPS,  Grade.SENIOR, 16,  9, "e13", ["K8s"],                     TaskStatus.IN_PROGRESS,  4),
        t("p3", "HR dashboard frontend",                Role.FRONTEND,Grade.JUNIOR, 24, 18, None, ["React"]),
        t("p3", "Editor validation tooling",            Role.UNITY,   Grade.MIDDLE, 16, 10, None, ["UI"]),
    ]
    # MobileQuest (p4)
    tasks += [
        t("p4", "iOS push notifications",               Role.MOBILE,  Grade.SENIOR, 16,  8, "e11", ["Native iOS"],             TaskStatus.IN_PROGRESS, 6),
        t("p4", "Daily quests UI",                      Role.MOBILE,  Grade.MIDDLE, 24, 14, None, ["Flutter"]),
        t("p4", "API for leaderboards",                 Role.BACKEND, Grade.MIDDLE, 20, 12, None, ["FastAPI"]),
        t("p4", "Mobile QA full pass",                  Role.QA,      Grade.MIDDLE, 32, 18, None, ["Mobile", "Regression"]),
    ]
    # AdminPanel-Acme (p5)
    tasks += [
        t("p5", "User management UI",                   Role.FRONTEND,Grade.MIDDLE, 32, 14, "e09", ["React", "TypeScript"],    TaskStatus.IN_PROGRESS, 10),
        t("p5", "Permissions page",                     Role.FRONTEND,Grade.JUNIOR, 24, 21, "e10", ["React"],                  TaskStatus.IN_PROGRESS, 6),
        t("p5", "Audit log API",                        Role.BACKEND, Grade.MIDDLE, 24, 14, None, ["FastAPI"]),
        t("p5", "Tailwind theming pass",                Role.FRONTEND,Grade.MIDDLE, 16, 10, None, ["Tailwind"]),
    ]

    # ---- Historical completed tasks (for past-performance signal) ----
    grade_speed_bias = {Grade.JUNIOR: 1.20, Grade.MIDDLE: 1.05, Grade.SENIOR: 0.95, Grade.LEAD: 0.90}
    for i in range(30):
        proj = rng.choice(projects)
        emp = rng.choice(employees)
        est = rng.choice([8, 16, 24, 32])
        bias = grade_speed_bias[emp.grade]
        actual = est * rng.uniform(bias - 0.15, bias + 0.15)
        days_ago = rng.randint(7, 80)
        counter["n"] += 1
        tasks.append(Task(
            id=f"t{counter['n']:03d}",
            project_id=proj.id,
            title=f"[hist] {emp.role.value} task #{i}",
            required_role=emp.role,
            required_grade_min=emp.grade,
            estimate_hours=est,
            deadline=today - timedelta(days=days_ago),
            assignee_id=emp.id,
            spent_hours=actual,
            status=TaskStatus.DONE,
            tags=rng.sample(emp.skills, k=min(2, len(emp.skills))) if emp.skills else [],
        ))

    # ---- TimeLogs (derived from spent_hours, spread across days) ----
    timelogs: list[TimeLog] = []
    for task in tasks:
        if task.spent_hours <= 0 or task.assignee_id is None:
            continue
        days = max(1, int(task.spent_hours / 4))
        per_day = task.spent_hours / days
        end = min(task.deadline, today) if task.status == TaskStatus.DONE else today
        for d_offset in range(days):
            log_date = end - timedelta(days=d_offset)
            timelogs.append(TimeLog(
                employee_id=task.assignee_id,
                task_id=task.id,
                project_id=task.project_id,
                date=log_date,
                hours=per_day,
            ))

    # ---- Time off (vacations, sick days) ----
    timeoffs = [
        # Senior Unreal off in 5 days for a week — affects p2 capacity
        TimeOff(employee_id="e05", start_date=today + timedelta(days=5),
                end_date=today + timedelta(days=11), type="vacation"),
        # Junior frontend on sick leave today + tomorrow
        TimeOff(employee_id="e10", start_date=today,
                end_date=today + timedelta(days=1), type="sick"),
        # Game designer pre-booked vacation in 2 weeks
        TimeOff(employee_id="e14", start_date=today + timedelta(days=12),
                end_date=today + timedelta(days=18), type="vacation"),
    ]

    # ---- Public holidays in window ----
    holidays = [
        Holiday(date=today + timedelta(days=4), name="Public holiday"),
    ]

    return WorldState(
        today=today,
        employees=employees,
        projects=projects,
        tasks=tasks,
        timelogs=timelogs,
        timeoffs=timeoffs,
        holidays=holidays,
    )
