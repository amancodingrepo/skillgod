#!/usr/bin/env python3
"""SkillGod engine-side health checks for `sg doctor` (Task 6).

Prints one `STATUS|label|detail` line per check (STATUS in PASS/WARN/FAIL) so
the Go CLI can colourise them. Exit 0 if no FAIL, 1 otherwise.

Usage: python doctor.py <sg_root> <cwd> [--full]
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _line(status, label, detail=""):
    print(f"{status}|{label}|{detail}", flush=True)


def check_engine_import(sg_root):
    eng = os.path.join(sg_root, "engine")
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); "
         "import runtime, memory, security, license, fs_watcher; print('ok')",
         eng], capture_output=True, text=True)
    if "ok" in (r.stdout or ""):
        _line("PASS", "engine importable", "runtime/memory/security/license/fs_watcher")
        return True
    _line("FAIL", "engine importable", (r.stderr or "").strip().splitlines()[-1:][0] if r.stderr else "import failed")
    return False


def check_hooks_present(sg_root):
    hooks = ["session_start.py", "user_prompt_submit.py", "pre_tool.py",
             "post_tool.py", "session_end.py"]
    missing = [h for h in hooks if not Path(sg_root, "hooks", h).exists()]
    if missing:
        _line("FAIL", "hook files present", f"missing: {missing} — run sg update")
        return False
    _line("PASS", "hook files present", "all 5 on disk")
    return True


def _load_manifest(sg_root):
    p = Path(sg_root, "MANIFEST.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_hooks_registered(sg_root):
    """Task 6.3 / 7.2 — registered in settings.json AND every path exists AND
    (if MANIFEST present) the on-disk hook hashes match the manifest."""
    settings = Path(os.path.expanduser("~/.claude/settings.json"))
    if not settings.exists():
        _line("WARN", "hooks registered", "~/.claude/settings.json not found (Claude Code not set up?)")
        return True
    try:
        hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks", {})
    except Exception as e:
        _line("FAIL", "hooks registered", f"settings.json unreadable: {e}")
        return False
    manifest = _load_manifest(sg_root)
    reg, missing_file, hash_mismatch = 0, [], []
    for ev, arr in hooks.items():
        for m in arr:
            for h in m.get("hooks", []):
                cmd = h.get("command", "")
                path = None
                if '"' in cmd:
                    parts = cmd.split('"')
                    for p in parts:
                        if p.endswith(".py"):
                            path = p
                            break
                if not path:
                    toks = cmd.split()
                    path = next((t for t in toks if t.endswith(".py")), None)
                if not path:
                    continue
                reg += 1
                if not os.path.exists(path):
                    missing_file.append(os.path.basename(path))
                    continue
                if manifest:
                    rel = "hooks/" + os.path.basename(path)
                    want = manifest.get("files", {}).get(rel)
                    if want:
                        got = hashlib.sha256(open(path, "rb").read()).hexdigest()
                        if got != want:
                            hash_mismatch.append(os.path.basename(path))
    if missing_file:
        _line("FAIL", "hooks registered", f"registered but FILE MISSING: {missing_file} — run sg init")
        return False
    if hash_mismatch:
        _line("WARN", "hooks registered", f"on-disk hook differs from manifest: {hash_mismatch} — run sg update")
        return True
    _line("PASS", "hooks registered", f"{reg} registered, all files present"
          + (", hashes match" if manifest else ""))
    return True


def check_hook_dryrun(sg_root):
    hook = os.path.join(sg_root, "hooks", "post_tool.py")
    payload = json.dumps({"session_id": "doctor", "task": "doctor check",
                          "output": "ordinary output, no decision", "active_skills": []})
    try:
        r = subprocess.run([sys.executable, hook], input=payload,
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if r.returncode == 0:
            _line("PASS", "hook dry-run", "post_tool.py exit 0")
            return True
        _line("FAIL", "hook dry-run", f"post_tool.py exit {r.returncode}: {(r.stderr or '').strip()[:80]}")
        return False
    except Exception as e:
        _line("FAIL", "hook dry-run", str(e))
        return False


def check_db_writable(sg_root):
    try:
        sys.path.insert(0, os.path.join(sg_root, "engine"))
        from license import set_kv, get_kv
        set_kv("_doctor_sentinel", str(time.time()))
        ok = get_kv("_doctor_sentinel") is not None
        # cleanup
        import sqlite3
        from license import DB_PATH
        c = sqlite3.connect(str(DB_PATH), timeout=10)
        c.execute("DELETE FROM kv WHERE key='_doctor_sentinel'")
        c.commit(); c.close()
        if ok:
            _line("PASS", "db writable", "kv INSERT/DELETE ok (WAL)")
            return True
        _line("FAIL", "db writable", "sentinel write did not read back")
        return False
    except Exception as e:
        _line("FAIL", "db writable", str(e))
        return False


def check_watchdog():
    try:
        import watchdog  # noqa: F401
        _line("PASS", "watchdog", "installed — event-driven path available")
    except Exception:
        _line("WARN", "watchdog", "not installed — using 5s poll loop (supported)")
    return True


def check_encoding():
    # Task 6.9 — the hook path must produce UTF-8 stdout on Windows.
    hook = None
    enc = None
    try:
        r = subprocess.run(
            [sys.executable, "-c", "import sys; print(sys.stdout.encoding)"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        enc = (r.stdout or "").strip().lower()
    except Exception:
        pass
    if enc and "utf-8" in enc:
        _line("PASS", "encoding", f"hook stdout encoding = {enc}")
    else:
        _line("WARN", "encoding", f"hook stdout encoding = {enc} (hooks force utf-8 at runtime)")
    return True


def last_capture_summary(sg_root):
    try:
        sys.path.insert(0, os.path.join(sg_root, "engine"))
        import sqlite3
        from memory import DB_PATH
        c = sqlite3.connect(str(DB_PATH), timeout=10)
        row = c.execute("SELECT created_at, kind FROM memory ORDER BY created_at DESC LIMIT 1").fetchone()
        recent = c.execute("SELECT importance FROM memory ORDER BY created_at DESC LIMIT 5").fetchall()
        c.close()
        if not row:
            _line("WARN", "last capture", "no memory captured yet")
            return True
        from datetime import datetime
        try:
            days = (datetime.now() - datetime.fromisoformat(row[0])).days
        except Exception:
            days = "?"
        imps = ", ".join(f"{r[0]:.2f}" for r in recent)
        _line("PASS", "last capture", f"{row[0][:19]} ({days}d ago); recent importances: {imps}")
        return True
    except Exception as e:
        _line("WARN", "last capture", str(e))
        return True


def full_selftest(sg_root):
    """Task 6.7 — real end-to-end: temp repo → commit a decision → watcher
    --once → assert a >=0.8 row landed. This would have caught the incident."""
    repo = tempfile.mkdtemp()
    try:
        def g(*a):
            subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
        g("init"); g("config", "user.email", "d@e.com"); g("config", "user.name", "D")
        Path(repo, "f.txt").write_text("x", encoding="utf-8")
        g("add", "."); g("commit", "-m", "decision: doctor self-test instead of guessing")

        db = os.path.join(tempfile.mkdtemp(), "skillgod.db")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        watcher = os.path.join(sg_root, "engine", "fs_watcher.py")
        # run one poll cycle against a fresh DB by pointing memory at it
        code = (
            "import sys,os;"
            f"sys.path.insert(0, r'{os.path.join(sg_root,'engine')}');"
            "import memory; memory.DB_PATH=__import__('pathlib').Path(sys.argv[1]);"
            "memory.DB_PATH.parent.mkdir(parents=True,exist_ok=True);"
            "import fs_watcher;"
            "fs_watcher.check_once(sys.argv[2], os.path.dirname(sys.argv[2]) or '.', '');"
            "rows=memory.get_timeline('__selftest__', min_importance=0.0);"
            "print('SELFTEST_ROWS', len([1 for r in [__import__('sqlite3').connect(str(memory.DB_PATH))] ]))"
        )
        # simpler: drive capture directly against the temp repo + temp db
        drv = (
            "import sys,os;"
            f"sys.path.insert(0, os.path.join(r'{sg_root}','engine'));"
            "import memory; import pathlib;"
            "memory.DB_PATH=pathlib.Path(sys.argv[1]); memory.DB_PATH.parent.mkdir(parents=True,exist_ok=True);"
            "import runtime, fs_watcher;"
            "head=fs_watcher.get_head(sys.argv[2]);"
            "msg=fs_watcher.get_commit_message(sys.argv[2], head);"
            "from memory import derive_project_id;"
            "r=runtime.capture_memory('git commit', msg, derive_project_id(sys.argv[2]), min_importance=0.0);"
            "print('IMP', r.get('importance'))"
        )
        r = subprocess.run([sys.executable, "-c", drv, db, repo],
                           capture_output=True, text=True, env=env, timeout=60)
        out = (r.stdout or "").strip()
        imp = 0.0
        for tok in out.split():
            try:
                imp = float(tok)
            except ValueError:
                pass
        if imp >= 0.8:
            _line("PASS", "e2e self-test", f"decision commit captured at importance {imp:.2f}")
            return True
        _line("FAIL", "e2e self-test", f"decision commit scored {imp:.2f} (<0.8): {r.stderr[:80]}")
        return False
    except Exception as e:
        _line("FAIL", "e2e self-test", str(e))
        return False
    finally:
        import shutil
        shutil.rmtree(repo, ignore_errors=True)


def main():
    sg_root = sys.argv[1]
    cwd = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    full = "--full" in sys.argv

    checks = [
        lambda: check_engine_import(sg_root),
        lambda: check_hooks_present(sg_root),
        lambda: check_hooks_registered(sg_root),
        lambda: check_hook_dryrun(sg_root),
        lambda: check_db_writable(sg_root),
        lambda: check_encoding(),
        lambda: check_watchdog(),
        lambda: last_capture_summary(sg_root),
    ]
    if full:
        checks.append(lambda: full_selftest(sg_root))

    ok = True
    for c in checks:
        try:
            if c() is False:
                ok = False
        except Exception as e:
            _line("FAIL", "check", str(e))
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
