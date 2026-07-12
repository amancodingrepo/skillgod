#!/usr/bin/env python3
"""
SkillGodRuntime — the one class that combines all three pillars.

Memory (claude-mem) + Skills (superpowers) + Agents (ruflo) = SkillGod

This is the file that wires everything together.
Every hook, every MCP tool, every CLI command calls this.
"""

import os, re, json, sys
import threading, platform, urllib.request
from pathlib import Path
from datetime import datetime

from memory  import (save, save_decision, save_pattern, save_error,
                     save_with_git,
                     get_recent, get_relevant, format_for_injection,
                     start_session, end_session, increment_task_count, stats,
                     derive_project_id)
from skills  import (find_skills, inject_skills, load_instincts,
                     build_augmented_prompt, learn_skill, stocktake,
                     rebuild_index)
from security import security_scan
from agents  import SkillGodSwarm, decompose_task, detect_agent_type
from signals import (record_no_rework, record_rework, count_rework_signals,
                     is_enabled as signals_enabled)
from variants import auto_enqueue_candidates


# ─────────────────────────────────────────────
# Anonymous CLI telemetry — fire-and-forget, never blocks the CLI.
# Powers the admin monitoring dashboard (/admin/monitoring).
# ─────────────────────────────────────────────

def _sg_version() -> str:
    v = os.environ.get("SKILLGOD_VERSION", "")
    if v:
        return v
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
    except Exception:
        return ""


def _detect_ide() -> str:
    if os.environ.get("SKILLGOD_IDE"):
        return os.environ["SKILLGOD_IDE"]
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR"):
        return "Cursor"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
        return "Claude Code"
    if os.environ.get("ANTIGRAVITY"):
        return "Antigravity"
    return os.environ.get("TERM_PROGRAM", "")


def _track_cli_event(command: str):
    """POST a CLI event to the API. Swallows every error — must never block sg."""
    api = os.environ.get("SKILLGOD_API", "")
    if not api:
        return
    try:
        from license import get_install_id
        install_id = get_install_id()
    except Exception:
        return
    payload = json.dumps({
        "install_id": install_id,
        "command":    command,
        "version":    _sg_version(),
        "ide":        _detect_ide(),
        "os":         platform.system().lower(),
    }).encode()
    try:
        req = urllib.request.Request(
            f"{api.rstrip('/')}/v1/internal/track-cli",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass  # never block the CLI


def track_cli(command: str):
    """Public entry point — spawn a daemon thread so the CLI never waits.

    PRIVACY FIX (BUG-038) — CLI telemetry is now gated on the same opt-in as
    quality signals. Previously it fired whenever SKILLGOD_API was set,
    regardless of consent, contradicting the "nothing leaves your machine
    unless you turn it on" promise."""
    try:
        from signals import is_enabled as _signals_enabled
        if not _signals_enabled():
            return
    except Exception:
        return  # can't verify consent — send nothing
    threading.Thread(target=_track_cli_event, args=(command,), daemon=True).start()


# ─────────────────────────────────────────────
# Memory capture from an AI response — shared by SkillGodRuntime.on_post_tool
# AND hooks/post_tool.py so both capture identically under the SAME project id.
# (Previously on_post_tool held this logic but NO hook ever called it, so
# decision→memory capture was dead in production; post_tool.py only recorded
# signals.)
# ─────────────────────────────────────────────

_DECISION_SIGNALS = [
    r"\bchose\b", r"\bdecided\b", r"\bwe will\b", r"\balways use\b",
    r"\bnever use\b", r"\bstandard approach\b", r"\barchitecture\b",
    r"\bconvention\b", r"\bpattern is\b", r"\bapproach is\b",
]


def capture_memory(task: str, output: str, project: str,
                   session_id: str = "") -> dict:
    """
    Detect an architectural decision in `output` and persist it to memory,
    keyed to `project`; then attempt to learn a reusable skill from the
    task/output pair. Returns {"memory": id|None, "skill": path|None}.
    Pure of any in-process runtime state so a fresh hook process can call it.
    """
    captured = {"memory": None, "skill": None}

    hits = sum(1 for p in _DECISION_SIGNALS if re.search(p, output.lower()))
    if hits >= 1:
        sentences = re.split(r'[.!?]\s+', output)
        summary   = next(
            (s.strip() for s in sentences if len(s.strip()) > 20),
            output[:120]
        )
        # BUG FIX — was save_decision(), which never tags git branch/commit.
        # save_with_git() already has exactly this logic (it just never got
        # wired into the real, hook-driven capture path) — same kind and
        # importance save_decision() used, so this is a drop-in swap, not a
        # behavior change beyond adding the git tag to `detail`.
        captured["memory"] = save_with_git(
            summary[:200], detail=output[:500], kind="decision",
            project=project, importance=0.9, session_id=session_id)

    learned = learn_skill(task, output, project=project)
    if learned:
        captured["skill"] = str(learned)

    return captured


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
        # BUG-B FIX — key the project the SAME way the hooks do: git-remote /
        # abspath-hash via derive_project_id(). Previously this read
        # SKILLGOD_PROJECT (baked into .mcp.json as the ENGINE INSTALL dir name),
        # so the MCP path keyed every project on the machine to one shared
        # bucket while hooks kept them isolated. One resolver now, in memory.py.
        self.project    = project or derive_project_id()
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
        track_cli("session_start")   # fire-and-forget telemetry
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
        import time as _time
        _t0     = _time.perf_counter()
        skills  = find_skills(task)
        _ms     = (_time.perf_counter() - _t0) * 1000
        self.last_fired_skills = skills   # Layer 2: remember for post_tool signal
        if self.verbose:
            try:
                from skills import _load_all_skills
                _total = len(_load_all_skills())
            except Exception:
                _total = 0
            print(f"[SkillGod] Scoring {_total:,} skills... done in {_ms:.0f}ms")
            if skills:
                print("→ Injecting before Claude sees your prompt...")
                chain = " → ".join(
                    f"{sk['name']} ({sk.get('score', 0):.2f})" for sk in skills
                )
                print(f"[SkillGod] {chain} → injected")

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
        # Decision→memory + skill learning (shared with hooks/post_tool.py).
        captured = capture_memory(task, output, self.project)
        if self.verbose:
            if captured.get("memory"):
                print(f"[SkillGod] Decision saved to memory #{captured['memory']}")
            if captured.get("skill"):
                print(f"[SkillGod] Learned skill → {Path(captured['skill']).name}")

        # ── Layer 2: signal recording ──────────────────────────────────────
        if signals_enabled() and self.last_fired_skills:
            # BUG-039 FIX — only scan the USER's text for rework intent. The
            # AI's own output routinely contains words like "instead" or
            # "actually", which counted as rework and unfairly dinged the
            # active skills' quality scores.
            rework = count_rework_signals(task)
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
            except Exception as e:
                print(f"[SkillGod] skill promotion failed: {e}", file=sys.stderr)

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