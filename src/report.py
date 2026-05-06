"""Deterministic Discord report.

Used as both:
  - the production output when no LLM is available
  - the ground-truth reference the LLM has to match in tone and content.
"""
from __future__ import annotations
from .models import WorldState, TaskStatus
from .analytics import (
    bench_risk, overloaded, project_margin_actual,
    grade_mismatches, expensive_on_low_margin, employee_workload_window,
    upcoming_time_off, partially_allocated_tasks,
)
from .matching import find_best_assignees


_TIMEOFF_LABEL = {"vacation": "🌴 отпуск", "sick": "🤒 больничный", "dayoff": "📅 отгул"}


def _proj_name(state, pid):
    p = next((x for x in state.projects if x.id == pid), None)
    return p.name if p else pid


def build_deterministic_report(state: WorldState) -> str:
    today = state.today
    L: list[str] = []
    L.append(f"# 🤖 Resource Allocation — {today.isoformat()}")
    L.append("")

    # --- 1. Bench risk ---
    L.append("## ⚠️ Bench risk (низкая загрузка следующие 2 недели)")
    br = bench_risk(state, days=14, threshold=0.6)
    if not br:
        L.append("_Никого. Все ребята загружены ≥60%._")
    else:
        # roll-up summary line first
        roles = {}
        for w in br:
            roles.setdefault(w["role"], 0)
            roles[w["role"]] += 1
        roll = ", ".join(f"{cnt} {role}" for role, cnt in roles.items())
        L.append(f"Через 2 недели частично освобождаются: {roll}")
        L.append("")
        for w in br:
            L.append(
                f"- **{w['employee_name']}** ({w['role']} / {w['grade']}): "
                f"util {int(w['utilization']*100)}%, свободно ~{w['free_hours']}ч"
            )
    L.append("")

    # --- 2. Overload ---
    L.append("## 🔥 Overload (нагрузка выше capacity)")
    ov = overloaded(state, days=14, threshold=1.0)
    if not ov:
        L.append("_Перегруженных нет._")
    else:
        for w in ov:
            L.append(
                f"- **{w['employee_name']}** ({w['role']} / {w['grade']}): "
                f"util {int(w['utilization']*100)}%, "
                f"committed {w['committed_hours']}ч / capacity {w['capacity_hours']}ч"
            )
            for tk in w.get("at_risk_tasks", []):
                L.append(f"   • риск дедлайна: «{tk['title']}» — до {tk['deadline']}, "
                         f"осталось {tk['remaining_hours']}ч")
    L.append("")

    # --- 3. Margin / efficiency ---
    L.append("## 💰 Маржа и эффективность")
    margins = [project_margin_actual(state, p.id) for p in state.projects]
    margins.sort(key=lambda m: m["delta_vs_target"])
    for m in margins:
        delta = m["delta_vs_target"]
        sign = "✅" if delta >= 0 else "❌"
        L.append(
            f"- {sign} **{m['project_name']}**: "
            f"факт {int(m['margin_actual']*100)}% / цель {int(m['margin_target']*100)}% "
            f"(Δ {int(delta*100):+d} п.п., revenue ~${int(m['revenue'])})"
        )

    gm = grade_mismatches(state)
    if gm:
        L.append("")
        L.append("**Senior делает junior-задачи (потеря маржи):**")
        for x in gm:
            L.append(f"- {x['employee']} ({x['employee_grade']}) → "
                     f"«{x['task_title']}» (нужен {x['required_min_grade']}+)")

    el = expensive_on_low_margin(state)
    if el:
        L.append("")
        L.append("**Дорогие сотрудники на низкомаржинальном проекте:**")
        for x in el:
            L.append(f"- {x['employee']} (${x['cost_per_hour']}/ч) на «{x['project']}» — "
                     f"{x['hours_last_n_days']}ч за {x['lookback_days']} дней")
    L.append("")

    # --- 4. Recommendations for unassigned / partially allocated tasks ---
    L.append("## 🎯 Рекомендации по нераспределённым задачам")
    unassigned = [t for t in state.tasks if t.is_unassigned and t.status != TaskStatus.DONE]
    unassigned.sort(key=lambda t: t.deadline)
    if not unassigned:
        L.append("_Нет открытых задач без исполнителя._")
    else:
        for task in unassigned[:12]:
            cands = find_best_assignees(state, task, top_k=2)
            proj = _proj_name(state, task.project_id)
            if not cands:
                L.append(f"- ⚠️ «{task.title}» ({proj}, до {task.deadline.isoformat()}) "
                         f"— **нет подходящих кандидатов** (роль {task.required_role.value} / "
                         f"≥{task.required_grade_min.value})")
                continue
            top = cands[0]
            second = cands[1] if len(cands) > 1 else None
            L.append(
                f"- «{task.title}» ({proj}, {task.estimate_hours}ч, "
                f"до {task.deadline.isoformat()})\n"
                f"   → **{top['employee_name']}** — match {int(top['score']*100)}% — {top['rationale']}"
                + (f"\n   _альтернатива: {second['employee_name']} — match {int(second['score']*100)}%_"
                   if second else "")
            )
    L.append("")

    # --- 4b. Partially-allocated tasks (need extra people) ---
    partial = partially_allocated_tasks(state)
    if partial:
        L.append("## ➕ Нужны дополнительные исполнители (частично распределённые)")
        for p in partial:
            assigned = ", ".join(p["allocated_to"])
            L.append(
                f"- «{p['task_title']}» ({p['project_name']}, до {p['deadline']}): "
                f"уже на задаче — {assigned}; не хватает **{p['unallocated_hours']:.0f}ч** "
                f"({p['required_role']} ≥{p['required_grade_min']})"
            )
        L.append("")

    # --- 5. Upcoming time off ---
    L.append("## 🌴 Скоро в отпуске / на больничном")
    tos = upcoming_time_off(state, days=14)
    if not tos:
        L.append("_Никто не уходит в ближайшие 2 недели._")
    else:
        for x in tos:
            label = _TIMEOFF_LABEL.get(x["type"], x["type"])
            L.append(f"- {label}: **{x['employee_name']}** ({x['role']}) — "
                     f"{x['start_date']} → {x['end_date']} ({x['days']} дн.)")
    L.append("")

    # --- 6. Free for new tasks ---
    L.append("## 🆓 Свободны для новых задач")
    free = [employee_workload_window(state, e, 14) for e in state.employees]
    free = [w for w in free if w["utilization"] < 0.7]
    free.sort(key=lambda x: x["utilization"])
    if not free:
        L.append("_Все загружены ≥70% — без переприоритизации новые задачи лучше не накидывать._")
    else:
        for w in free[:8]:
            L.append(
                f"- {w['employee_name']} ({w['role']} / {w['grade']}): "
                f"util {int(w['utilization']*100)}%, свободно ~{w['free_hours']}ч в ближайшие 2 недели"
            )

    return "\n".join(L)
