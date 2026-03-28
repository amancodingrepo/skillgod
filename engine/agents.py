#!/usr/bin/env python3
"""
SkillGod Agent Layer
Architecture from ruflo (swarm) + agency-agents (specialist roster) + ralph (loop)

Key capability: per-agent skill injection.
Each spawned agent gets skills relevant to ITS task, not the parent task.
Nobody else does this. This is the moat.
"""

import re, json
from pathlib import Path
from dataclasses import dataclass, field

VAULT_DIR = Path(__file__).parent.parent / "vault"

# Specialist agent types — from agency-agents roster
AGENT_TYPES = {
    "frontend":      ["ui", "ux", "react", "css", "html", "component",
                      "layout", "design", "responsive", "animation"],
    "backend":       ["api", "database", "server", "auth", "endpoint",
                      "rest", "graphql", "sql", "python", "node"],
    "devops":        ["deploy", "docker", "ci", "cd", "kubernetes",
                      "terraform", "aws", "pipeline", "infrastructure"],
    "security":      ["security", "audit", "vulnerability", "injection",
                      "owasp", "penetration", "scan", "threat"],
    "reviewer":      ["review", "pr", "pull request", "code quality",
                      "refactor", "smell", "lint", "standard"],
    "test":          ["test", "testing", "playwright", "jest", "pytest",
                      "coverage", "e2e", "unit", "integration"],
    "docs":          ["document", "readme", "docs", "comment", "explain",
                      "technical writing", "specification"],
    "research":      ["research", "analyse", "investigate", "summarise",
                      "search", "compare", "evaluate"],
    "design":        ["ui design", "figma", "wireframe", "prototype",
                      "visual", "typography", "color", "ux research"],
}


@dataclass
class AgentTask:
    id:          str
    task:        str
    agent_type:  str
    skills:      list[dict] = field(default_factory=list)
    status:      str = "pending"   # pending | running | done | failed
    result:      str = ""
    error:       str = ""


@dataclass
class SwarmResult:
    tasks:       list[AgentTask]
    combined:    str = ""
    memories:    list[str] = field(default_factory=list)


# ─────────────────────────────────────────────
# TASK DECOMPOSITION (ruflo hive-mind pattern)
# ─────────────────────────────────────────────

def detect_agent_type(task: str) -> str:
    """Classify a task to the best agent type."""
    task_lower = task.lower()
    scores = {}
    for agent, keywords in AGENT_TYPES.items():
        scores[agent] = sum(1 for kw in keywords if kw in task_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "backend"


def decompose_task(task: str) -> list[dict]:
    """
    Break a complex task into subtasks for specialist agents.
    Simple heuristic decomposition — no LLM call needed for this.
    Returns list of {task, agent_type} dicts.
    """
    task_lower = task.lower()
    subtasks   = []

    # Detect if this is a full-stack task needing multiple agents
    needs_frontend = any(w in task_lower for w in
                         ["ui", "page", "landing", "frontend", "interface",
                          "design", "component", "layout", "form"])
    needs_backend  = any(w in task_lower for w in
                         ["api", "endpoint", "database", "backend", "server",
                          "auth", "login", "register", "save", "store"])
    needs_test     = any(w in task_lower for w in
                         ["test", "testing", "e2e", "coverage", "spec"])
    needs_docs     = any(w in task_lower for w in
                         ["document", "readme", "docs", "spec", "write up"])

    if needs_frontend and needs_backend:
        # Full-stack decomposition
        subtasks.append({
            "task":       f"Frontend: {task}",
            "agent_type": "frontend",
            "id":         "agent-fe-1",
        })
        subtasks.append({
            "task":       f"Backend: {task}",
            "agent_type": "backend",
            "id":         "agent-be-1",
        })
        if needs_test:
            subtasks.append({
                "task":       f"Tests: {task}",
                "agent_type": "test",
                "id":         "agent-test-1",
            })
    elif needs_frontend:
        subtasks.append({
            "task":       task,
            "agent_type": "frontend",
            "id":         "agent-fe-1",
        })
        if needs_test:
            subtasks.append({
                "task":       f"Tests for: {task}",
                "agent_type": "test",
                "id":         "agent-test-1",
            })
    else:
        # Single agent — detect best type
        agent_type = detect_agent_type(task)
        subtasks.append({
            "task":       task,
            "agent_type": agent_type,
            "id":         f"agent-{agent_type}-1",
        })

    if needs_docs and not any(s["agent_type"] == "docs" for s in subtasks):
        subtasks.append({
            "task":       f"Documentation: {task}",
            "agent_type": "docs",
            "id":         "agent-docs-1",
        })

    return subtasks if subtasks else [{
        "task": task, "agent_type": "backend", "id": "agent-1"
    }]


# ─────────────────────────────────────────────
# PER-AGENT SKILL INJECTION (the unique capability)
# ─────────────────────────────────────────────

def get_skills_for_agent(agent_type: str, task: str,
                          top_k: int = 3) -> list[dict]:
    """
    Score skills specifically for an agent type + task combination.
    Frontend agent gets UI skills. Backend agent gets API skills.
    This is what nobody else does.
    """
    from skills import find_skills  # local import to avoid circular

    # Build an agent-aware query: combine agent keywords + actual task
    agent_keywords = " ".join(AGENT_TYPES.get(agent_type, [])[:4])
    agent_query    = f"{agent_keywords} {task}"

    return find_skills(agent_query, top_k=top_k)


# ─────────────────────────────────────────────
# RALPH LOOP PATTERN
# ─────────────────────────────────────────────

def should_continue_loop(output: str, task: str) -> bool:
    """
    From ralph: detect if task is genuinely done or needs another iteration.
    Returns True if loop should continue, False if done.
    """
    output_lower = output.lower()
    task_lower   = task.lower()

    # Strong completion signals
    done_signals = [
        "task complete", "done", "finished", "all items completed",
        "prd complete", "implementation complete", "tests passing",
        "successfully", "all tests pass"
    ]
    if any(s in output_lower for s in done_signals):
        return False

    # Continuation signals — loop should keep going
    continue_signals = [
        "still working", "in progress", "next step", "continuing",
        "remaining tasks", "todo", "not yet", "needs more"
    ]
    if any(s in output_lower for s in continue_signals):
        return True

    # Check if output seems incomplete (no code/results if task expected them)
    if ("implement" in task_lower or "build" in task_lower or
            "create" in task_lower):
        has_code = "```" in output or "def " in output or "function" in output
        if not has_code and len(output.split()) < 100:
            return True

    return False  # default: assume done


class RalphLoop:
    """
    Autonomous loop from ralph — run until task genuinely complete.
    Has circuit breaker to prevent infinite loops.
    """

    def __init__(self, max_iterations: int = 10):
        self.max_iterations = max_iterations
        self.iterations     = 0
        self.history        = []

    def should_stop(self, output: str, task: str) -> bool:
        self.iterations += 1
        if self.iterations >= self.max_iterations:
            return True  # circuit breaker
        return not should_continue_loop(output, task)

    def record(self, task: str, output: str) -> None:
        self.history.append({"task": task, "output": output[:200],
                             "iteration": self.iterations})


# ─────────────────────────────────────────────
# SWARM ORCHESTRATOR (ruflo hive-mind)
# ─────────────────────────────────────────────

class SkillGodSwarm:
    """
    Lightweight swarm coordinator.
    Decomposes tasks, assigns specialist agents with per-agent skills.
    Runs agents sequentially (parallel support coming with asyncio upgrade).
    """

    def __init__(self, execute_fn=None):
        """
        execute_fn: callable(task: str, skills: list, memory: str) -> str
        Pass in your actual LLM call function.
        If None, swarm operates in dry-run mode (returns task plans only).
        """
        self.execute = execute_fn

    def plan(self, task: str) -> list[AgentTask]:
        """Decompose task into agent assignments with skill injection."""
        subtasks = decompose_task(task)
        agents   = []
        for s in subtasks:
            skills  = get_skills_for_agent(s["agent_type"], s["task"])
            agents.append(AgentTask(
                id         = s["id"],
                task       = s["task"],
                agent_type = s["agent_type"],
                skills     = skills,
            ))
        return agents

    def run(self, task: str, memory_context: str = "") -> SwarmResult:
        """Run full swarm for a task. Returns combined results."""
        agents = self.plan(task)

        for agent in agents:
            if not self.execute:
                agent.status = "dry-run"
                agent.result = f"[Would run {agent.agent_type} agent on: {agent.task[:60]}]"
                continue

            # Build augmented prompt for this specific agent
            from skills import inject_skills
            augmented = inject_skills(agent.task, agent.skills)
            if memory_context:
                augmented = memory_context + "\n\n" + augmented

            try:
                agent.result = self.execute(agent.task, agent.skills,
                                            memory_context)
                agent.status = "done"
            except Exception as e:
                agent.status = "failed"
                agent.error  = str(e)

        # Combine results
        combined = "\n\n---\n\n".join(
            f"**{a.agent_type} agent:**\n{a.result}"
            for a in agents if a.result
        )

        # Extract memories from results
        memories = []
        for a in agents:
            if a.status == "done" and a.result:
                memories.append(f"[{a.agent_type}] {a.task[:80]}")

        return SwarmResult(tasks=agents, combined=combined, memories=memories)

    def describe_plan(self, task: str) -> str:
        """Describe what agents would be spawned, without running."""
        agents = self.plan(task)
        lines  = [f"Swarm plan for: {task[:60]}"]
        for a in agents:
            skill_names = [s.get("name", "?") for s in a.skills[:2]]
            skills_str  = ", ".join(skill_names) if skill_names else "no skills matched"
            lines.append(f"  {a.id:<20} [{a.agent_type}]  skills: {skills_str}")
        return "\n".join(lines)


if __name__ == "__main__":
    import sys
    task = " ".join(sys.argv[1:]) or "build a landing page with contact form"

    swarm = SkillGodSwarm()  # dry-run mode
    print(swarm.describe_plan(task))
    print()
    result = swarm.run(task)
    for agent in result.tasks:
        print(f"[{agent.agent_type}] {agent.status}: {agent.result}")