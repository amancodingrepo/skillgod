#!/usr/bin/env python3
"""Task 5.3 — a unicode commit message must round-trip byte-identical through
the git read path → capture → SQLite → get_timeline (the mojibake regression:
`â€”` for em-dash on Windows because git output was decoded as cp1252)."""
import os
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

UNICODE_MSG = "decision: use — em-dash, naïve, 日本語 storage instead of Redis"


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True)


def test_unicode_commit_roundtrip():
    import pathlib
    import memory
    from fs_watcher import get_commit_message, get_head

    repo = tempfile.mkdtemp()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "i18n.commitEncoding", "utf-8")
    (pathlib.Path(repo) / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", ".")
    # commit with the unicode message via a file to avoid shell encoding issues
    msg_file = os.path.join(repo, "_msg.txt")
    open(msg_file, "w", encoding="utf-8").write(UNICODE_MSG)
    _git(repo, "commit", "-F", msg_file)

    # 1) git read path returns the message byte-identical
    head = get_head(repo)
    read_msg = get_commit_message(repo, head)
    assert read_msg == UNICODE_MSG, f"git read mangled it: {read_msg!r}"

    # 2) capture into an isolated DB, then read back from SQLite via get_timeline
    memory.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "skillgod.db"
    memory.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    import runtime
    r = runtime.capture_memory(task="git commit", output=read_msg,
                               project="utf8-proj", min_importance=0.0)
    assert r["memory"], "should have captured the decision"

    tl = memory.get_timeline("utf8-proj", min_importance=0.0)
    assert tl, "timeline should have the row"
    # summary is the subject line — must be byte-identical (no mojibake)
    assert tl[0]["summary"] == UNICODE_MSG, f"stored: {tl[0]['summary']!r}"
    assert "â€”" not in tl[0]["summary"], "cp1252 mojibake present!"
    print(f"  round-trip OK: {tl[0]['summary']!r}")


if __name__ == "__main__":
    try:
        test_unicode_commit_roundtrip()
        print("  PASS  test_unicode_commit_roundtrip")
        sys.exit(0)
    except AssertionError as e:
        print(f"  FAIL  {e}")
        sys.exit(1)
