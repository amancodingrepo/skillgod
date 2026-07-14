#!/usr/bin/env python3
"""
SkillGod filesystem/git watcher — baseline memory capture for IDEs that have no
hooks equivalent (Cursor, Windsurf, and any future IDE without a push mechanism).

Independent of any IDE or model: watches a target project's git state and, on a
new commit or branch switch, runs the same capture_memory() decision-signal
heuristic the real hooks use. Verified to fire correctly on decision-language
commits and stay silent on ordinary ones, entirely without any IDE or model in
the loop.

EVENT-DRIVEN (research adoption 1.1): when the optional `watchdog` package is
installed, the watcher subscribes to real filesystem events on the repo's
`.git/HEAD` and `.git/logs/HEAD` and reacts the instant either changes — a
`git checkout` (rewrites `.git/HEAD`) or a `git commit`/merge/reset (appends to
`.git/logs/HEAD`) is picked up immediately rather than up to a full poll
interval later. `watchdog` is an OPTIONAL accelerator, deliberately NOT a hard
dependency: the local engine ships zero-dependency so the one-line installer
runs on a bare system Python, so if watchdog is absent the watcher falls back to
the original git-log poll loop unchanged. A slow safety-net poll still runs
underneath the event path to catch any event a platform drops. The capture
heuristic (check_once), self-healing restart (ensure_watcher_running),
per-project isolation (watcher_paths), and idempotency are all unchanged by
this — only the *reaction mechanism* changed, not what gets captured.

This is a narrower capture surface than the hooks: it only sees what a
developer commits to git, not what the AI reasoned about mid-session. It's a
baseline, not a replacement for real hook support landing on these tools.

Started by `sg init` (via `sg watch --daemon`) as a detached background
process, NOT an OS-level service — it does not survive a machine reboot on
its own. Instead, ensure_watcher_running() below is wired into every hot-path
entry point that already touches SkillGod (hooks/session_start.py,
hooks/pre_tool.py, every MCP tool in mcp_server.py, and every `sg` CLI command
via cli/cmd/root.go's PersistentPreRunE) as a cheap opportunistic
check-and-restart. A watcher killed by a reboot silently repairs itself the
next time the user does ANYTHING that already goes through SkillGod — no
systemd/launchd/registry autostart entry needed. The honest tradeoff: a long
idle period with zero SkillGod usage after a reboot leaves the watcher off
until the next real interaction; it is not proactively restarted on boot
itself.

Usage:
  python fs_watcher.py <project_dir> <engine_dir> [--once] [--baseline SHA]
                       [--poll-interval SECONDS] [--stop-sentinel PATH]
                       [--pid-file PATH] [--force-poll]

  --once             single poll cycle then exit (used by the deterministic
                     test harness — avoids racing a poll interval)
  --baseline SHA     start from an explicit HEAD instead of the directory's
                     current HEAD (also test-harness support)
  --stop-sentinel    if this file exists at the top of any poll cycle, delete
                     it and exit cleanly — the cooperative shutdown mechanism
                     `sg watch --stop` uses (works identically on every OS, no
                     platform-specific signal handling required)
  --pid-file         write our own PID here at startup, remove it on any exit
                     path (clean or not) so `sg watch --status` never reports
                     a stale run as live
  --force-poll       skip the event-driven path even if watchdog is installed
                     (used by the deterministic test harness to exercise the
                     fallback poll loop)
"""
import argparse
import hashlib
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

LOCK_STALE_SECONDS = 10  # see clear_stale_lock() — mirrors cli/cmd/watch.go's
# lockStaleAfter constant; both sides must agree since either language can be
# the one holding (or reclaiming) this lock.


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [fs_watcher] {msg}", flush=True)


# Windows: every subprocess call in this file (git polling, every few
# seconds, for the life of the watcher) must suppress console allocation —
# DETACHED_PROCESS on the watcher's own spawn only covers the watcher itself,
# not the git.exe children it spawns internally on each poll tick.
# creationflags is a Windows-only subprocess kwarg — passing it at all (even
# as 0) raises ValueError on POSIX, so it's only added to kwargs on Windows.
_GIT_KWARGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}


def get_head(repo_dir: str) -> str:
    """Current HEAD sha, or '' if git isn't installed, the dir isn't a repo
    (yet, or not anymore — e.g. .git got removed mid-run), or any other git
    error. Never raises — a watcher that crashes on a transient git error
    defeats the point of running unattended in the background."""
    try:
        return subprocess.check_output(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=10,
            **_GIT_KWARGS,
        ).strip()
    except FileNotFoundError:
        return ""  # git not installed
    except Exception:
        return ""  # not a repo (yet/anymore), detached weirdness, etc.


def get_commit_message(repo_dir: str, sha: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", repo_dir, "log", "-1", "--pretty=%B", sha],
            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace", timeout=10,
            **_GIT_KWARGS,
        ).strip()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────
# Self-healing startup — ensure_watcher_running() and its helpers.
#
# Called from every hot-path entry point that already touches SkillGod:
# hooks/session_start.py, hooks/pre_tool.py, and the top of every MCP tool in
# mcp_server.py. cli/cmd/watch.go implements the SAME scheme independently in
# Go (ensureWatcherStarted) for the CLI-invocation entry point, sharing the
# exact same on-disk path/lock conventions so a Go `sg` command and a Python
# hook/MCP call racing on the same project are mutually exclusive without
# either needing to know the other exists.
# ─────────────────────────────────────────────────────────────────────────

def watcher_paths(sg_root: str, project_dir: str) -> tuple[str, str, str]:
    """Same hash-of-abspath scheme as cli/cmd/watch.go's watcherHash()/
    watcherPaths() — MUST stay byte-for-byte identical (lowercased abspath,
    sha256, first 12 hex chars) so both languages compute the same file names
    for the same project directory."""
    abs_dir = os.path.abspath(project_dir)
    h = hashlib.sha256(abs_dir.lower().encode("utf-8")).hexdigest()[:12]
    d = os.path.join(sg_root, "db", "watchers")
    return (os.path.join(d, h + ".pid"),
            os.path.join(d, h + ".stop"),
            os.path.join(d, h + ".log"))


def _project_id_for(project_dir: str) -> str:
    """Single source of truth — the SAME derive_project_id() hooks/MCP/CLI use.
    Never reimplement the id scheme here."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from memory import derive_project_id
        return derive_project_id(project_dir)
    except Exception:
        return ""


def _is_git_repo(project_dir: str) -> bool:
    """True if project_dir is inside a git working tree (walks up for .git)."""
    try:
        d = os.path.abspath(project_dir)
        while True:
            if os.path.exists(os.path.join(d, ".git")):
                return True
            parent = os.path.dirname(d)
            if parent == d:
                return False
            d = parent
    except Exception:
        return False


def _write_pid_record(pid_file: str, project_dir: str, pid: int) -> None:
    """Write the JSON watcher record (matches cli/cmd/watch.go's watcherRecord)
    so liveness can be verified against the right project, not just the pid."""
    import json as _json
    rec = {"pid": pid, "project_dir": os.path.abspath(project_dir),
           "project_id": _project_id_for(project_dir),
           "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        Path(pid_file).parent.mkdir(parents=True, exist_ok=True)
        Path(pid_file).write_text(_json.dumps(rec), encoding="utf-8")
    except Exception:
        pass


def _read_pid(pid_file: str):
    """Read the pid from a watcher record — JSON (new) or bare int (legacy)."""
    try:
        raw = Path(pid_file).read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None
    if raw.startswith("{"):
        try:
            import json as _json
            return int(_json.loads(raw).get("pid"))
        except Exception:
            return None
    try:
        return int(raw)
    except Exception:
        return None


def _is_process_alive(pid) -> bool:
    if not pid or pid <= 0:
        return False
    if platform.system() == "Windows":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    else:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, just owned by someone else
        except Exception:
            return False


def _clear_stale_lock(lock_file: str) -> None:
    """A crashed holder must not permanently block every future self-heal
    attempt for this project — the guarded section is just a pid-file read
    plus maybe a spawn, never a wait, so any lock older than this is
    abandoned, not legitimately in use."""
    try:
        if os.path.exists(lock_file) and (time.time() - os.path.getmtime(lock_file)) > LOCK_STALE_SECONDS:
            os.remove(lock_file)
    except Exception:
        pass


def _start_detached(sg_root: str, project_dir: str, pid_file: str, stop_file: str, log_file: str) -> None:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    watcher_script = os.path.join(sg_root, "engine", "fs_watcher.py")
    engine_dir = os.path.join(sg_root, "engine")
    py = sys.executable or ("python" if platform.system() == "Windows" else "python3")
    args = [py, watcher_script, os.path.abspath(project_dir), engine_dir,
            "--pid-file", pid_file, "--stop-sentinel", stop_file]
    logf = open(log_file, "a", encoding="utf-8", errors="replace")
    kwargs = dict(stdout=logf, stderr=logf, stdin=subprocess.DEVNULL)
    if platform.system() == "Windows":
        # DETACHED_PROCESS alone does not reliably suppress the console for a
        # console-subsystem executable like python.exe — Windows can still
        # briefly flash a conhost.exe window at spawn time. CREATE_NO_WINDOW
        # is the flag that actually prevents any window/console allocation.
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                    | subprocess.DETACHED_PROCESS
                                    | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(args, **kwargs)
    # Written immediately from the parent as a JSON record (Task 2) — no window
    # where a concurrent caller sees "no pid file" right after the spawn. The
    # child rewrites the identical record shortly after starting.
    _write_pid_record(pid_file, project_dir, proc.pid)


def ensure_watcher_running(project_dir: str, sg_root: str = None) -> None:
    """
    Cheap opportunistic self-heal, called at the top of every hot-path entry
    point (SessionStart, PreToolUse, every MCP tool call). If a watcher is
    already alive for this project: no-op, return immediately (one small file
    read + one liveness check — negligible latency, measured in this
    session's verification). If not (missing pid file, stale pid, or a
    confirmed-dead process — e.g. killed across a reboot): starts one via the
    same detached-spawn path `sg init`/`sg watch --daemon` use, then returns
    without waiting on it — the caller's real request is never blocked on this.

    Race-safe across BOTH concurrent Python callers (two hooks firing close
    together) AND a concurrent Go `sg` invocation: the guard is a lock file
    (pid_file + ".lock") created with O_CREAT|O_EXCL, which is atomic at the
    OS level regardless of which process or language created it — see
    cli/cmd/watch.go's ensureWatcherStarted for the Go side of this same
    scheme, using the identical path convention.

    Never raises — a self-heal hiccup must never break the caller's actual
    request (a session starting, a tool firing, an MCP call responding).
    """
    try:
        if sg_root is None:
            sg_root = str(Path(__file__).resolve().parent.parent)
        # Task 2b — never start a watcher for a non-repo (e.g. a home dir).
        if not _is_git_repo(project_dir):
            return
        pid_file, stop_file, log_file = watcher_paths(sg_root, project_dir)

        pid = _read_pid(pid_file)
        if pid and _is_process_alive(pid):
            return  # fast path — already running

        lock_file = pid_file + ".lock"
        Path(lock_file).parent.mkdir(parents=True, exist_ok=True)
        _clear_stale_lock(lock_file)
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            return  # another caller (Python or Go) is already handling this
        try:
            # Re-check under the lock — another racer may have finished
            # starting it between our first check and acquiring the lock.
            pid = _read_pid(pid_file)
            if pid and _is_process_alive(pid):
                return
            if os.path.exists(pid_file):
                os.remove(pid_file)  # stale — safe to clear, we hold the lock
            _start_detached(sg_root, project_dir, pid_file, stop_file, log_file)
        finally:
            try:
                os.remove(lock_file)
            except Exception:
                pass
    except Exception:
        pass  # self-heal must never break the caller's real request


def check_once(repo_dir: str, engine_dir: str, last_sha: str) -> str:
    """One poll cycle. Returns the HEAD sha this cycle observed (== last_sha
    if nothing changed, or if git/the repo is currently unavailable)."""
    sys.path.insert(0, engine_dir)
    from memory import derive_project_id
    from runtime import capture_memory  # same function the real hooks use

    head = get_head(repo_dir)
    if not head or head == last_sha:
        return last_sha or head

    msg = get_commit_message(repo_dir, head)
    if not msg:
        # HEAD moved but we couldn't read the message (race with an in-flight
        # commit, or a merge commit git couldn't format in time) — don't drop
        # the sha; the NEXT cycle will just see no change and stay quiet. We
        # intentionally do not retry the current cycle to keep poll cycles cheap.
        return head

    try:
        project = derive_project_id(repo_dir)
        # min_importance=0.0 → EVERY commit is captured, never silently dropped
        # (Task 1). The timeline filters by importance at read time.
        result = capture_memory(task=f"git commit {head[:8]}", output=msg,
                                project=project, min_importance=0.0)
        imp = result.get("importance", 0.0)
        markers = result.get("markers") or []
        mtxt = ("matched: " + ", ".join(repr(m) for m in markers)) if markers else "no decision markers"
        mem = result.get("memory")
        tail = f" — captured #{mem}" if mem else ""
        if imp < 0.6:
            tail += " (below timeline default)"
        _log(f"commit {head[:8]} on project={project}: importance={imp:.2f} ({mtxt}){tail}")
    except Exception as e:
        # A capture-layer hiccup must never crash the watcher — there's no
        # supervisor to restart it, and dying silently in the background is
        # worse than skipping one commit's capture.
        _log(f"capture_memory failed for {head[:8]}: {e}")

    return head


# ─────────────────────────────────────────────────────────────────────────
# Event-driven watch (research adoption 1.1) — watchdog on .git/HEAD +
# .git/logs/HEAD. Optional accelerator; falls back to poll_loop() if watchdog
# is not installed. Both paths funnel every reaction through the SAME
# check_once() so capture behavior is identical regardless of trigger.
# ─────────────────────────────────────────────────────────────────────────

# Files inside .git whose modification means HEAD moved. `.git/HEAD` is
# rewritten on a branch switch (its content is `ref: refs/heads/<branch>`);
# `.git/logs/HEAD` is appended on EVERY head movement (commit, checkout, merge,
# reset, rebase), so watching both catches commits and branch switches alike.
_GIT_HEAD_TRIGGERS = ("HEAD", os.path.join("logs", "HEAD"))

# Safety-net poll cadence used UNDERNEATH the event path — slow on purpose, it
# only exists to catch an event a platform silently dropped. The fast reaction
# comes from the filesystem event, not this.
_EVENT_SAFETY_POLL_SECONDS = 30.0

# Debounce: a single git operation can emit several rapid fs events (git writes
# .git/HEAD, .git/logs/HEAD, a lock file, then renames). Collapse a burst into
# one check_once() so one checkout doesn't trigger five captures.
_EVENT_DEBOUNCE_SECONDS = 0.15


def _watchdog_available() -> bool:
    try:
        import watchdog  # noqa: F401
        return True
    except Exception:
        return False


def poll_loop(project_dir: str, engine_dir: str, last_sha: str,
              poll_interval: float, stop_sentinel: str) -> None:
    """Original interval-poll loop — the fallback path when watchdog is absent,
    preserved byte-for-byte in behavior. Also the platform-independent backstop
    the event path leans on for its slow safety-net poll."""
    while True:
        if stop_sentinel and os.path.exists(stop_sentinel):
            _log("stop sentinel found — shutting down cleanly")
            try:
                os.remove(stop_sentinel)
            except Exception:
                pass
            return
        last_sha = check_once(project_dir, engine_dir, last_sha)
        time.sleep(poll_interval)


def event_loop(project_dir: str, engine_dir: str, last_sha: str,
               stop_sentinel: str) -> bool:
    """
    Event-driven watch on the repo's .git HEAD state via watchdog. Returns True
    if it ran (watchdog present and a .git dir existed), False if the caller
    should fall back to poll_loop(). Reacts to a real filesystem event on
    .git/HEAD or .git/logs/HEAD the instant it lands, then runs the SAME
    check_once() the poll path uses. A slow safety-net poll runs underneath to
    recover any dropped event; the stop-sentinel is honored on both paths.
    """
    if not _watchdog_available():
        return False

    git_dir = os.path.join(os.path.abspath(project_dir), ".git")
    if not os.path.isdir(git_dir):
        # No .git yet (repo not initialized). Poll path handles the "repo
        # appears later" case; don't claim the event path here.
        return False

    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    import threading

    state = {"last_sha": last_sha}
    lock = threading.Lock()
    wake = threading.Event()   # set by fs events; the worker waits on it

    def _is_head_trigger(path: str) -> bool:
        try:
            rel = os.path.relpath(os.path.abspath(path), git_dir)
        except Exception:
            return False
        return rel in _GIT_HEAD_TRIGGERS

    class _HeadHandler(FileSystemEventHandler):
        def on_any_event(self, event):
            # Directory events and unrelated files (index, ORIG_HEAD, packed
            # objects) are ignored — only HEAD / logs/HEAD movements matter.
            if getattr(event, "is_directory", False):
                return
            for p in (getattr(event, "src_path", ""),
                      getattr(event, "dest_path", "")):
                if p and _is_head_trigger(p):
                    wake.set()
                    return

    observer = Observer()
    # Watch the whole .git dir recursively so logs/HEAD (one level down) is
    # covered; the handler filters down to just the two HEAD files.
    observer.schedule(_HeadHandler(), git_dir, recursive=True)
    observer.daemon = True
    observer.start()
    _log(f"event-driven watch active (watchdog) on {git_dir}")

    def _react():
        with lock:
            state["last_sha"] = check_once(project_dir, engine_dir, state["last_sha"])

    try:
        while True:
            if stop_sentinel and os.path.exists(stop_sentinel):
                _log("stop sentinel found — shutting down cleanly")
                try:
                    os.remove(stop_sentinel)
                except Exception:
                    pass
                return True
            # Block until either a filesystem event fires (fast path) or the
            # safety-net interval elapses (slow backstop). This is what makes
            # reaction latency ~debounce, not ~poll-interval.
            fired = wake.wait(timeout=_EVENT_SAFETY_POLL_SECONDS)
            if fired:
                wake.clear()
                time.sleep(_EVENT_DEBOUNCE_SECONDS)  # collapse the event burst
                wake.clear()  # swallow any events that arrived during debounce
            _react()
    except KeyboardInterrupt:
        _log("interrupted — shutting down")
        return True
    finally:
        try:
            observer.stop()
            observer.join(timeout=2)
        except Exception:
            pass


def main() -> None:
    p = argparse.ArgumentParser(description="SkillGod filesystem/git memory watcher")
    p.add_argument("project_dir")
    p.add_argument("engine_dir")
    p.add_argument("--once", action="store_true")
    p.add_argument("--baseline", default=None)
    # Task 3 — poll loop is a blessed, supported path (watchdog is an optional
    # accelerator that's usually absent). Default 5s, override with
    # SKILLGOD_POLL_INTERVAL or --poll-interval.
    _default_poll = 5.0
    try:
        _default_poll = float(os.environ.get("SKILLGOD_POLL_INTERVAL", "5.0"))
    except Exception:
        _default_poll = 5.0
    p.add_argument("--poll-interval", type=float, default=_default_poll)
    p.add_argument("--stop-sentinel", default=None)
    p.add_argument("--pid-file", default=None)
    p.add_argument("--force-poll", action="store_true",
                   help="skip the event-driven path even if watchdog is "
                        "installed (used by the deterministic test harness to "
                        "exercise the fallback poll loop)")
    args = p.parse_args()

    # Task 2b — never watch a non-repo (evidence: a watcher polled C:\\Users\\Asus
    # indefinitely). Refuse before writing a pid file or entering any loop.
    if not _is_git_repo(args.project_dir):
        _log(f"{args.project_dir} is not inside a git repository — watcher not started")
        return

    if args.pid_file:
        try:
            _write_pid_record(args.pid_file, args.project_dir, os.getpid())
        except Exception as e:
            _log(f"could not write pid file {args.pid_file}: {e}")

    def _cleanup_pid_file():
        if args.pid_file:
            try:
                Path(args.pid_file).unlink(missing_ok=True)
            except Exception:
                pass

    last_sha = args.baseline if args.baseline is not None else get_head(args.project_dir)
    _log(f"watching {args.project_dir} (baseline HEAD={last_sha[:8] if last_sha else 'none'})")

    if args.once:
        new_head = check_once(args.project_dir, args.engine_dir, last_sha)
        _log(f"HEAD after this poll: {new_head[:8] if new_head else 'none'}")
        _cleanup_pid_file()
        return

    try:
        ran_event = False
        if not args.force_poll:
            # Fast path: real filesystem events on .git HEAD state. Returns
            # False (without consuming the loop) if watchdog is missing or there
            # is no .git yet, so we transparently fall back to polling.
            ran_event = event_loop(args.project_dir, args.engine_dir,
                                   last_sha, args.stop_sentinel)
        if not ran_event:
            # Task 3 — split the old ambiguous "watchdog unavailable or no .git"
            # into two distinct, actionable messages. The no-.git case already
            # exited above (Task 2b), so here it's specifically about watchdog.
            if not args.force_poll and not _watchdog_available():
                _log(f"watchdog not installed — using poll loop "
                     f"(interval {args.poll_interval:g}s)")
            poll_loop(args.project_dir, args.engine_dir, last_sha,
                      args.poll_interval, args.stop_sentinel)
    except KeyboardInterrupt:
        _log("interrupted — shutting down")
    finally:
        _cleanup_pid_file()


if __name__ == "__main__":
    main()
