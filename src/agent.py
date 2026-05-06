"""LLM agent loop.

The agent gets the tools from `tools.make_tools(state)` and is asked to produce
the Discord report. If `ANTHROPIC_API_KEY` is not set, falls back to the
deterministic report (which is what would also run if the API is down).
"""
from __future__ import annotations
import json
import os
import time
from typing import Any
from .models import WorldState
from .tools import make_tools
from .report import build_deterministic_report


SYSTEM_PROMPT = """\
Ты — Resource Allocation Agent геймдев-студии. Твоя задача — собрать
ежедневный отчёт для тимлида в Discord на основе данных, которые
возвращают tools. Не выдумывай числа: всё, что появляется в отчёте, должно
быть получено из tools.

План работы:
1. Вызови get_bench_risk, get_overloaded, get_all_project_margins,
   get_grade_mismatches, get_expensive_on_low_margin, list_unassigned_tasks,
   get_partially_allocated_tasks, get_upcoming_time_off.
2. Для каждой нераспределённой задачи вызови find_assignees(top_k=2).
3. Сформируй markdown-отчёт со следующими секциями (с эмодзи и заголовками):
   - ⚠️ Bench risk (через 1-2 недели низкая загрузка)
   - 🔥 Overload (нагрузка выше capacity, с задачами под риском дедлайна)
   - 💰 Маржа и эффективность (по проектам, плюс senior-on-junior и
     дорогие сотрудники на низкомаржинальных проектах)
   - 🎯 Рекомендации по нераспределённым задачам (имя + match% + краткая причина)
   - ➕ Частично распределённые задачи (если есть — кто уже на задаче и сколько часов не закрыто)
   - 🌴 Скоро в отпуске / на больничном (если есть)
   - 🆓 Свободны для новых задач

При обсуждении availability учитывай, что capacity уже включает поправку
на отпуска и праздники — не нужно вычитать их повторно.

Стиль: компактно, по-русски, маркированные списки. Финальный ответ —
готовый текст для отправки в Discord, без преамбул вроде "вот отчёт".
"""


def run_agent(state: WorldState, max_iterations: int = 15, verbose: bool = False) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        if verbose:
            print("[agent] ANTHROPIC_API_KEY not set — using deterministic fallback")
        return build_deterministic_report(state)

    try:
        import anthropic
    except ImportError:
        if verbose:
            print("[agent] anthropic package not installed — using deterministic fallback")
        return build_deterministic_report(state)

    client = anthropic.Anthropic(api_key=api_key)
    specs, handlers = make_tools(state)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Сформируй сегодняшний отчёт по ресурсам команды."},
    ]

    for i in range(max_iterations):
        # Retry transient errors (529 Overloaded, 503, network blips) with backoff.
        resp = None
        for attempt in range(8):
            try:
                resp = client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=specs,
                    messages=messages,
                )
                break
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
                status = getattr(e, "status_code", None)
                if status in (429, 500, 502, 503, 529) or isinstance(e, anthropic.APIConnectionError):
                    delay = min(60, 2 ** attempt)  # cap at 60s
                    if verbose:
                        print(f"[agent] API {status or 'connection error'}, retry {attempt+1}/8 in {delay}s")
                    time.sleep(delay)
                    continue
                raise
        if resp is None:
            if verbose:
                print("[agent] API overloaded after retries — using deterministic fallback")
            return build_deterministic_report(state)

        if verbose:
            print(f"[agent] iter={i} stop_reason={resp.stop_reason}")

        if resp.stop_reason == "end_turn":
            return "".join(b.text for b in resp.content if b.type == "text")

        # Handle tool_use blocks
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                handler = handlers.get(block.name)
                try:
                    result = handler(**block.input) if handler else {"error": f"unknown tool {block.name}"}
                except Exception as e:
                    result = {"error": str(e)}
                if verbose:
                    print(f"[agent]   tool={block.name} input={block.input}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user",      "content": tool_results})

    return "[agent] exceeded max_iterations — please check logs"
