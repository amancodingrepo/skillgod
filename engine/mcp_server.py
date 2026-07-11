#!/usr/bin/env python3
"""
SkillGod MCP Server
Exposes the full runtime as MCP tools.
Claude Code and Antigravity connect to this via localhost:3333.

Start:  python engine/mcp_server.py
Config: add to ~/.claude/settings.json mcpServers section
"""

import os, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Install FastMCP: pip install fastmcp")
    sys.exit(1)

from runtime import get_runtime
from security import security_scan
from skills  import find_skills, stocktake, rebuild_index
from memory  import get_recent, save, stats as mem_stats

mcp = FastMCP("skillgod")

import sqlite3


def _project() -> str:
    """
    BUG-B FIX — resolve the project id FRESH on every tool call from the current
    working directory, via the SAME derive_project_id() the hooks use. Never
    cached at server startup.

    The old code created a module-global runtime once at import, keyed to
    os.environ["SKILLGOD_PROJECT"] — which cli/cmd/init.go baked into .mcp.json
    as the ENGINE INSTALL dir name. So every project on the machine collapsed
    into one shared memory bucket via MCP, while hooks (which use
    derive_project_id()) kept projects isolated: the two subsystems disagreed
    on identity. Deriving per call, from cwd, makes them agree.
    """
    from memory import derive_project_id
    return derive_project_id()


def _rt():
    """
    Runtime bound to the freshly-resolved project. get_runtime() rebuilds only
    when the project actually changes, so repeat calls in the same directory
    reuse the instance, yet a call from a different directory never serves a
    stale project id held over from the previous call.
    """
    return get_runtime(project=_project())


def _self_heal_watcher() -> None:
    """
    Self-healing watcher startup — called as the first line of every
    @mcp.tool() function (an explicit one-line call in each, not a wrapping
    decorator, so FastMCP's parameter-schema introspection on the tool
    functions is never at risk of being disturbed). ~0.1ms when a watcher is
    already running for this project (measured); starts one via the same
    detached-spawn path `sg init`/`sg watch --daemon` use if not, then returns
    immediately without waiting on it. Never raises — see
    engine/fs_watcher.py's ensure_watcher_running() docstring for the full
    rationale and the race-safety guarantee shared with hooks/session_start.py,
    hooks/pre_tool.py, and cli/cmd/root.go.
    """
    try:
        from fs_watcher import ensure_watcher_running
        ensure_watcher_running(os.getcwd())
    except Exception:
        pass

_UPGRADE_PROMPT = (
    "\n\n[SkillGod Free — 30 skills active. "
    "Upgrade for 1,927 skills: skillgod.dev/pricing]"
)


def _get_license_tier() -> str:
    """
    FIX 8 — return 'pro' or 'free' from the local kv store (set by
    session_start.py's online check). No network call; falls back to 'free'
    if the kv key is missing or unreadable.
    """
    try:
        from license import get_local_db_path
        conn = sqlite3.connect(get_local_db_path())
        row = conn.execute(
            "SELECT value FROM kv WHERE key='license_status'"
        ).fetchone()
        conn.close()
        return row[0] if row else "free"
    except Exception:
        return "free"


@mcp.tool()
def sg_find_skills(task: str, top_k: int = 3) -> str:
    """
    Find skills relevant to a task.
    Returns scored skill list as JSON.
    Each entry includes 'matched': which triggers/tags fired and why.
    """
    _self_heal_watcher()
    threats = security_scan(task)
    if threats:
        return json.dumps({"blocked": True, "threats": threats})
    # FIX 8 — vault tier. find_skills() already scores against vault_free/ for
    # free users (see skills._get_active_vault_dir); here we surface the tier
    # and append an upgrade nudge so free users know more skills exist.
    tier = _get_license_tier()
    skills = find_skills(task, top_k=top_k)
    payload = json.dumps([{
        "name":        sk["name"],
        "score":       sk.get("score", 0),
        "description": sk.get("description", ""),
        "confidence":  sk.get("confidence", 0),
        "matched":     sk.get("matched", []),
    } for sk in skills])
    if tier == "free":
        return payload + _UPGRADE_PROMPT
    return payload


@mcp.tool()
def sg_inject_context(task: str) -> str:
    """
    Build an augmented prompt for a task.
    Includes: instincts + matched skills + relevant memory.
    Returns the full augmented prompt string.
    """
    _self_heal_watcher()
    result = _rt().on_pre_tool(task)
    if result is None:
        return "[SkillGod] Blocked: prompt injection detected."
    # FIX 8 — nudge free users that the full vault injects more context.
    if _get_license_tier() == "free":
        return result + _UPGRADE_PROMPT
    return result


@mcp.tool()
def sg_save_memory(summary: str, kind: str = "context",
                   project: str = "") -> str:
    """Save a memory item. kind: decision | pattern | error | context"""
    _self_heal_watcher()
    proj = project or _project()
    row_id = save(summary, kind=kind, project=proj)
    return f"Memory saved (id={row_id}, kind={kind}, project={proj})"


@mcp.tool()
def sg_get_memory(project: str = "", limit: int = 10) -> str:
    """Get recent memory for a project. Returns JSON array."""
    _self_heal_watcher()
    proj = project or _project()
    mems = get_recent(proj, limit=limit)
    return json.dumps(mems)


@mcp.tool()
def sg_learn_skill(task: str, output: str) -> str:
    """
    Attempt to learn a new skill from a task + output pair.
    Returns path to saved skill file, or 'not reusable'.
    """
    _self_heal_watcher()
    from skills import learn_skill
    path = learn_skill(task, output, project=_project())
    if path:
        return f"Skill learned → {Path(path).name}"
    return "Output did not meet reusability threshold."


@mcp.tool()
def sg_stocktake() -> str:
    """Audit the skill vault. Returns health report."""
    _self_heal_watcher()
    return stocktake()


@mcp.tool()
def sg_spawn_agents(task: str) -> str:
    """
    Decompose a complex task and spawn specialist agents.
    Each agent gets its own skill injection.
    Returns JSON with plan and results.
    """
    _self_heal_watcher()
    result = _rt().spawn(task)
    payload = json.dumps(result)
    # FIX 8 — spawned agents inject vault skills too; nudge free users.
    if _get_license_tier() == "free":
        return payload + _UPGRADE_PROMPT
    return payload


@mcp.tool()
def sg_plan_agents(task: str) -> str:
    """Preview how a task would be decomposed into agents, without running."""
    _self_heal_watcher()
    return _rt().plan_agents(task)


@mcp.tool()
def sg_security_scan(text: str) -> str:
    """Scan text for prompt injection patterns. Returns threat list or 'clean'."""
    _self_heal_watcher()
    threats = security_scan(text)
    if not threats:
        return "clean"
    return json.dumps({"threats": threats, "count": len(threats)})


@mcp.tool()
def sg_vault_stats() -> str:
    """Return vault and memory statistics."""
    _self_heal_watcher()
    result = _rt().vault_stats()
    return json.dumps(result, indent=2)


@mcp.tool()
def sg_rebuild_index() -> str:
    """Rebuild the SQLite skill index from vault files."""
    _self_heal_watcher()
    count = rebuild_index()
    return f"Index rebuilt — {count} skills indexed."


if __name__ == "__main__":
    # Banner goes to STDERR: with transport="stdio" the server never binds a
    # port — stdout IS the JSON-RPC channel, so any banner text there would
    # corrupt the MCP handshake. (The old code printed a bogus
    # "Starting on localhost:3333" to stdout; the server has never listened on
    # a port.)
    print("[SkillGod MCP] server ready (stdio transport)", file=sys.stderr)
    print(f"[SkillGod MCP] project: {_project()}", file=sys.stderr)
    print("[SkillGod MCP] tools: sg_find_skills, sg_inject_context, "
          "sg_save_memory, sg_get_memory, sg_learn_skill, sg_stocktake, "
          "sg_spawn_agents, sg_plan_agents, sg_security_scan, sg_vault_stats",
          file=sys.stderr)
    mcp.run(transport="stdio")
