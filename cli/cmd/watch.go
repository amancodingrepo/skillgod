package cmd

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

var watchCmd = &cobra.Command{
	Use:   "watch",
	Short: "Run the filesystem/git memory-capture watcher for this project",
	Long: `Baseline memory capture for IDEs with no hooks equivalent (Cursor,
Windsurf). Polls git in the current directory and captures decision-language
commits into local memory — independent of any IDE or model.

sg watch              run in the foreground (Ctrl+C to stop)
sg watch --daemon     start detached in the background, return immediately
sg watch --stop       stop the background watcher running for this directory
sg watch --status     report whether one is running for this directory`,
	RunE: runWatch,
}

var (
	watchDaemon bool
	watchStop   bool
	watchStatus bool
)

func init() {
	watchCmd.Flags().BoolVar(&watchDaemon, "daemon", false, "start detached in the background")
	watchCmd.Flags().BoolVar(&watchStop, "stop", false, "stop the watcher running for this directory")
	watchCmd.Flags().BoolVar(&watchStatus, "status", false, "show whether a watcher is running for this directory")
}

// ── State file layout ───────────────────────────────────────────────────────
// One watcher per (sgRoot, project directory) pair. State lives under
// sgRoot/db/watchers/<hash of abs project dir>.{pid,stop,log} — same tree as
// the rest of this install's local runtime state (db/skillgod.db lives
// alongside it), not scattered into the OS's own temp/service directories,
// since this is a per-project detached process, not an installed service.

func watcherHash(absDir string) string {
	sum := sha256.Sum256([]byte(strings.ToLower(absDir)))
	return hex.EncodeToString(sum[:])[:12]
}

func watcherPaths(sgRoot, cwd string) (pidFile, stopFile, logFile string) {
	abs, err := filepath.Abs(cwd)
	if err != nil {
		abs = cwd
	}
	h := watcherHash(abs)
	dir := filepath.Join(sgRoot, "db", "watchers")
	return filepath.Join(dir, h+".pid"), filepath.Join(dir, h+".stop"), filepath.Join(dir, h+".log")
}

func readPID(pidFile string) (int, bool) {
	data, err := os.ReadFile(pidFile)
	if err != nil {
		return 0, false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return 0, false
	}
	return pid, true
}

func runWatch(cmd *cobra.Command, args []string) error {
	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}
	cwd, err := os.Getwd()
	if err != nil {
		return err
	}
	pidFile, stopFile, _ := watcherPaths(sgRoot, cwd)

	if watchStop {
		return stopWatcherForDir(pidFile, stopFile)
	}
	if watchStatus {
		return reportWatcherStatus(pidFile)
	}

	if !watchDaemon {
		// Foreground: block, inherit this terminal's stdio, Ctrl+C stops it
		// (the Python side's KeyboardInterrupt handler cleans up the pid file).
		enginePath := filepath.Join(sgRoot, "engine", "fs_watcher.py")
		pyArgs := []string{enginePath, cwd, filepath.Join(sgRoot, "engine"),
			"--pid-file", pidFile, "--stop-sentinel", stopFile}
		c := exec.Command(pythonCmd(), pyArgs...)
		c.Stdout, c.Stderr, c.Stdin = os.Stdout, os.Stderr, os.Stdin
		return c.Run()
	}

	started, err := startProjectWatcher(sgRoot, cwd)
	if err != nil {
		return err
	}
	if !started {
		if pid, ok := readPID(pidFile); ok {
			fmt.Printf("Watcher already running for this directory (pid %d).\n", pid)
		}
	}
	return nil
}

// lockStaleAfter bounds how long a claim lock can be held before a caller
// assumes its owner crashed mid-decision and reclaims it. The guarded section
// is just a pid-file read + maybe a process spawn — never a wait — so a lock
// older than this is abandoned, not legitimately in use.
const lockStaleAfter = 10 * time.Second

// clearStaleLock removes an abandoned claim lock so a crashed holder can't
// permanently block every future self-heal attempt for this project.
func clearStaleLock(lockFile string) {
	info, err := os.Stat(lockFile)
	if err != nil {
		return
	}
	if time.Since(info.ModTime()) > lockStaleAfter {
		os.Remove(lockFile)
	}
}

// ensureWatcherStarted is the ONE race-safe check-then-spawn implementation,
// shared by every caller that might start a watcher for (sgRoot, cwd):
// `sg init`, `sg watch --daemon`, and the opportunistic self-heal check fired
// from root.go's PersistentPreRunE on every other `sg` command.
//
// Race safety: the guard is a plain lock FILE (pidFile + ".lock") created with
// O_CREATE|O_EXCL — atomic at the OS level regardless of which process or
// language created it. engine/fs_watcher.py's ensure_watcher_running() uses
// the EXACT same path convention and the same O_EXCL primitive, so a Go `sg`
// invocation and a Python hook/MCP-server call racing on the same project are
// mutually exclusive even though they're different processes in different
// languages — neither needs to know about the other, just this one file path.
//
// quiet suppresses the "Watcher started..." confirmation, for the self-heal
// path (fires on every `sg stats`-style command; printing there would be
// surprising noise for what's meant to be invisible plumbing). init/`sg watch
// --daemon` want the visible confirmation, so they pass quiet=false.
func ensureWatcherStarted(sgRoot, cwd string, quiet bool) (started bool, err error) {
	pidFile, stopFile, logFile := watcherPaths(sgRoot, cwd)

	if pid, ok := readPID(pidFile); ok && isProcessAlive(pid) {
		return false, nil // fast path — already running, no lock needed at all
	}

	lockFile := pidFile + ".lock"
	if err := os.MkdirAll(filepath.Dir(lockFile), 0755); err != nil {
		return false, err
	}
	clearStaleLock(lockFile)
	lf, lerr := os.OpenFile(lockFile, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if lerr != nil {
		// On a fresh install this directory now always exists (created just
		// above), so a real O_EXCL failure here means exactly one thing:
		// another caller (this process's sibling command, a hook, or the MCP
		// server — same file, doesn't matter which) is already handling this
		// exact race window. Back off; trust them to finish the start.
		return false, nil
	}
	lf.Close()
	defer os.Remove(lockFile)

	// Re-check under the lock: another racer may have finished starting it
	// between our first check (above) and acquiring the lock.
	if pid, ok := readPID(pidFile); ok && isProcessAlive(pid) {
		return false, nil
	}
	os.Remove(pidFile) // stale from a prior unclean exit (or a dead process
	// across a reboot) — safe to clear now that we hold the lock.

	enginePath := filepath.Join(sgRoot, "engine", "fs_watcher.py")
	pyArgs := []string{enginePath, cwd, filepath.Join(sgRoot, "engine"),
		"--pid-file", pidFile, "--stop-sentinel", stopFile}

	c, serr := spawnDetachedWatcher(pythonCmd(), pyArgs, logFile)
	if serr != nil {
		return false, serr
	}
	// Written immediately from the parent (not left to the child to
	// self-report on its own schedule) so there's no window, however brief,
	// where a concurrent caller could see "no pid file" right after we've
	// already spawned — the child overwrites this with the identical value
	// shortly after starting, which is a harmless no-op.
	_ = os.WriteFile(pidFile, []byte(strconv.Itoa(c.Process.Pid)), 0644)

	if !quiet {
		fmt.Printf("Watcher started in background (pid %d). Logs: %s\n", c.Process.Pid, logFile)
		fmt.Println("Stop with: sg watch --stop")
	}
	return true, nil
}

// startProjectWatcher is the visible-confirmation entry point used by `sg
// init` and `sg watch --daemon`.
func startProjectWatcher(sgRoot, cwd string) (started bool, err error) {
	return ensureWatcherStarted(sgRoot, cwd, false)
}

// selfHealWatcher is the silent, opportunistic entry point fired on every
// other `sg` command (root.go's PersistentPreRunE) and mirrors
// engine/fs_watcher.py's ensure_watcher_running() used by the Python hooks
// and the MCP server. Never surfaces an error to the caller — a self-heal
// hiccup must not break the user's actual command.
func selfHealWatcher() {
	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return
	}
	cwd, err := os.Getwd()
	if err != nil {
		return
	}
	_, _ = ensureWatcherStarted(sgRoot, cwd, true)
}

// spawnDetachedWatcher does the actual OS-level detached spawn — no pid-file
// writing, no printing; ensureWatcherStarted owns those so there's exactly
// one place that decides IF to spawn and one place that mechanically does it.
// Its stdout/stderr, which would otherwise vanish once the terminal that
// launched it is gone, is redirected to logFile.
func spawnDetachedWatcher(pyCmd string, pyArgs []string, logFile string) (*exec.Cmd, error) {
	if err := os.MkdirAll(filepath.Dir(logFile), 0755); err != nil {
		return nil, err
	}
	lf, err := os.OpenFile(logFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, err
	}
	c := exec.Command(pyCmd, pyArgs...)
	c.Stdout = lf
	c.Stderr = lf
	applyDetachAttrs(c)

	if err := c.Start(); err != nil {
		lf.Close()
		return nil, err
	}
	// Deliberately not calling c.Wait() — that would block the caller on the
	// (intentionally long-lived) child.
	return c, nil
}

func stopWatcherForDir(pidFile, stopFile string) error {
	pid, ok := readPID(pidFile)
	if !ok || !isProcessAlive(pid) {
		fmt.Println("No watcher is running for this directory.")
		os.Remove(pidFile)
		return nil
	}
	// Cooperative shutdown: the sentinel file, checked once per poll cycle, is
	// the SAME mechanism on every OS — no platform-specific signal handling
	// needed (Windows has no real SIGTERM equivalent for a plain child
	// process; this sidesteps that entirely).
	if err := os.WriteFile(stopFile, []byte("stop"), 0644); err != nil {
		return err
	}
	fmt.Print("Stopping watcher...")
	for i := 0; i < 20; i++ { // up to ~6s: comfortably above the 2s poll interval
		time.Sleep(300 * time.Millisecond)
		if _, stillThere := readPID(pidFile); !stillThere {
			fmt.Println(" stopped.")
			return nil
		}
	}
	fmt.Println()
	fmt.Println("Watcher did not confirm shutdown in time — it may still be finishing its current poll cycle.")
	return nil
}

func reportWatcherStatus(pidFile string) error {
	pid, ok := readPID(pidFile)
	if !ok || !isProcessAlive(pid) {
		fmt.Println("No watcher running for this directory.")
		return nil
	}
	fmt.Printf("Watcher running for this directory (pid %d).\n", pid)
	return nil
}
