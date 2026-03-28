#!/usr/bin/env python3
"""
SkillGodRuntime — the one class that combines all three pillars.

Memory (claude-mem) + Skills (superpowers) + Agents (ruflo) = SkillGod

This is the file that wires everything together.
Every hook, every MCP tool, every CLI command calls this.
"""

import os, re, json
from pathlib import Path
from datetime import datetime

from memory  import (save, save_decision, save_pattern, save_error,
                     get_recent, get_relevant, format_for_injection,
                     start_session, end_session, increment_task_count, stats)
from skills  import (find_skills, inject_skills, load_instincts,
                     build_augmented_prompt, learn_skill, stocktake,
                     rebuild_index)
from security import security_scan
from agents  import SkillGodSwarm, decompose_task, detect_agent_type
from signals import (record_no_rework, record_rework, count_rework_signals,
                     is_enabled as signals_enabled)
from variants import auto_enqueue_candidates


class SkillGodRuntime:
    """
    The combined runtime.

    Usage:
        rt = SkillGodRuntime(project="my-project")

        # Session start — returns context to prepend
        context = rt.on_session_start()

        # Before any tool use — returns augmented prompt
        augmented = rt.on_pre_tool(task)

        # After tool response — captures memory, maybe learns skill
        rt.on_post_tool(task, output)

        # Multi-agent task
        result = rt.spawn(task)
    """

    def __init__(self, project: str = None, session_id: str = None,
                 verbose: bool = False):
        self.project    = project or os.environ.get("SKILLGOD_PROJECT",
                                                     Path.cwd().name)
        self.session_id = session_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.verbose    = verbose
        self.swarm      = SkillGodSwarm()
        self.last_fired_skills: list[dict] = []   # Layer 2: track for signal recording

        if self.verbose:
            print(f"[SkillGod] Runtime started — project={self.project}")


    # ─────────────────────────────────────────
    # LIFECYCLE HOOKS (claude-mem pattern)
    # ─────────────────────────────────────────

    def on_session_start(self) -> str:
        """
        SessionStart hook.
        Load instincts + recent project memory.
        Returns string to inject into session context.
        """
        start_session(self.session_id, self.project)
        rebuild_index()

        instincts = load_instincts()
        memories  = get_recent(self.project, limit=8)
        mem_str   = format_for_injection(memories)

        parts = []
        if instincts:
            parts.append(instincts)
        if mem_str:
            parts.append(mem_str)

        if self.verbose:
            print(f"[SkillGod] Session start — "
                  f"{len(memories)} memories, instincts loaded")

        return "\n\n".join(parts)


    def on_pre_tool(self, task: str) -> str | None:
        """
        PreToolUse hook.
        1. Security scan
        2. Find relevant skills
        3. Get relevant memories
        4. Build augmented prompt
        Returns augmented prompt string, or None if blocked by security.
        """
        # Security first — always
        threats = security_scan(task)
        if threats:
            if self.verbose:
                print(f"[SkillGod] Security: {len(threats)} threat(s) detected")
            return None  # blocked

        increment_task_count(self.session_id)

        # Skills
        skills  = find_skills(task)
        self.last_fired_skills = skills   # Layer 2: remember for post_tool signal
        if self.verbose and skills:
            print(f"[SkillGod] Injecting {len(skills)} skill(s):")
            for sk in skills:
                print(f"  -> {sk['name']} (score={sk.get('score', 0):.2f})")

        # Relevant memory
        memories = get_relevant(task, self.project, limit=4)
        mem_str  = format_for_injection(memories) if memories else ""

        return build_augmented_prompt(task, skills=skills,
                                      memory_context=mem_str)


    def on_post_tool(self, task: str, output: str) -> dict:
        """
        PostToolUse hook.
        1. Detect decisions in output → save to memory
        2. Maybe learn new skill from output
        Returns dict with what was captured.
        """
        captured = {"memory": None, "skill": None}

        # Detect decision signals
        DECISION_SIGNALS = [
            r"\bchose\b", r"\bdecided\b", r"\bwe will\b", r"\balways use\b",
            r"\bnever use\b", r"\bstandard approach\b", r"\barchitecture\b",
            r"\bconvention\b", r"\bpattern is\b", r"\bapproach is\b",
        ]
        hits = sum(1 for p in DECISION_SIGNALS if re.search(p, output.lower()))

        if hits >= 1:
            sentences = re.split(r'[.!?]\s+', output)
            summary   = next(
                (s.strip() for s in sentences if len(s.strip()) > 20),
                output[:120]
            )
            mem_id = save_decision(summary[:200], detail=output[:500],
                                   project=self.project)
            captured["memory"] = mem_id
            if self.verbose:
                print(f"[SkillGod] Decision saved to memory #{mem_id}")

        # Maybe learn a skill
        learned = learn_skill(task, output, project=self.project)
        if learned:
            captured["skill"] = str(learned)
            if self.verbose:
                print(f"[SkillGod] Learned skill → {Path(learned).name}")

        # ── Layer 2: signal recording ──────────────────────────────────────
        if signals_enabled() and self.last_fired_skills:
            rework = count_rework_signals(task + " " + output[:500])
            for sk in self.last_fired_skills:
                sid  = sk.get("id") or sk.get("name", "unknown")
                name = sk.get("name", sid)
                if rework == 0:
                    record_no_rework(sid, name, self.session_id)
                else:
                    record_rework(sid, name, rework, self.session_id)
            if self.verbose:
                kind = "rework" if rework else "accept"
                print(f"[SkillGod] Signal recorded: {kind} "
                      f"({len(self.last_fired_skills)} skill(s))")

        # ── Layer 2: promotion queue scan (every ~10 sessions) ─────────────
        if hash(self.session_id) % 10 == 0:
            try:
                added = auto_enqueue_candidates()
                if added and self.verbose:
                    print(f"[SkillGod] {added} skill(s) queued for promotion review")
            except Exception:
                pass

        return captured


    def on_session_end(self, summary: str = "") -> None:
        """SessionEnd hook — finalise session record."""
        if not summary:
            mem = get_recent(self.project, limit=3)
            if mem:
                summary = "; ".join(m["summary"][:60] for m in mem[:3])
        end_session(self.session_id, summary)
        if self.verbose:
            print(f"[SkillGod] Session ended — {self.session_id}")


    # ─────────────────────────────────────────
    # MULTI-AGENT (ruflo + agency-agents)
    # ─────────────────────────────────────────

    def spawn(self, task: str) -> dict:
        """
        Spawn specialist agents for a complex task.
        Each agent gets its own skill injection.
        Returns dict with plan, results, memories.
        """
        threats = security_scan(task)
        if threats:
            return {"blocked": True, "threats": threats}

        plan = self.swarm.plan(task)

        if self.verbose:
            print(f"[SkillGod] Spawning {len(plan)} agent(s):")
            for a in plan:
                skill_names = [s.get("name", "?") for s in a.skills[:2]]
                print(f"  [{a.agent_type}] skills: {', '.join(skill_names)}")

        result = self.swarm.run(task)

        # Save agent results as memories
        for agent_task in result.tasks:
            if agent_task.status == "done":
                save_pattern(
                    f"[{agent_task.agent_type}] {agent_task.task[:80]}",
                    project=self.project
                )

        return {
            "plan":     [{"id": a.id, "type": a.agent_type,
                         "task": a.task, "status": a.status}
                        for a in result.tasks],
            "combined": result.combined,
            "memories": result.memories,
        }


    def plan_agents(self, task: str) -> str:
        """Preview agent decomposition without running."""
        return self.swarm.describe_plan(task)


    # ─────────────────────────────────────────
    # UTILITY
    # ─────────────────────────────────────────

    def vault_stats(self) -> dict:
        """Combined stats: memory + skills."""
        mem_stats   = stats(self.project)
        skill_audit = stocktake()
        return {
            "project":    self.project,
            "memory":     mem_stats,
            "skill_audit": skill_audit,
        }


    def scan(self, text: str) -> list[str]:
        """Expose security scanner."""
        return security_scan(text)


# ─────────────────────────────────────────────
# FACTORY
# ─────────────────────────────────────────────

_runtime: SkillGodRuntime | None = None

def get_runtime(project: str = None, verbose: bool = False) -> SkillGodRuntime:
    """Get or create the global runtime instance."""
    global _runtime
    if _runtime is None or (project and _runtime.project != project):
        _runtime = SkillGodRuntime(project=project, verbose=verbose)
    return _runtime


if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) or "debug this Python traceback"

    rt = SkillGodRuntime(project="demo", verbose=True)

    print("\n=== Session Start ===")
    ctx = rt.on_session_start()
    print(ctx or "(no context yet)")

    print("\n=== Pre Tool ===")
    augmented = rt.on_pre_tool(task)
    if augmented:
        print(augmented[:400] + "..." if len(augmented) > 400 else augmented)
    else:
        print("BLOCKED by security scan")

    print("\n=== Agent Plan ===")
    print(rt.plan_agents(task))