package cmd

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

// killPID terminates a process cross-platform (Windows: TerminateProcess via
// os.Process.Kill; POSIX: SIGKILL). Best effort.
func killPID(pid int) {
	if pid <= 0 {
		return
	}
	if p, err := os.FindProcess(pid); err == nil {
		_ = p.Kill()
	}
}

// watcherRecord is the JSON payload written into <hash>.pid (Task 2). It
// replaces the bare-integer pid file so liveness can be verified against the
// RIGHT project, not just "some process with this pid exists". Legacy bare-int
// files are still read (treated as unverifiable → reaped and restarted).
type watcherRecord struct {
	PID        int    `json:"pid"`
	ProjectDir string `json:"project_dir"`
	ProjectID  string `json:"project_id"`
	StartedAt  string `json:"started_at"`
}

// readWatcherRecord parses a pid file as JSON (new format) or a bare int
// (legacy). ok=false when the file is missing/garbage. legacy=true when it was
// a bare int (no project info → caller should reap+restart to get a verifiable
// record).
func readWatcherRecord(pidFile string) (rec watcherRecord, legacy bool, ok bool) {
	data, err := os.ReadFile(pidFile)
	if err != nil {
		return rec, false, false
	}
	s := strings.TrimSpace(string(data))
	if strings.HasPrefix(s, "{") {
		if json.Unmarshal([]byte(s), &rec) == nil && rec.PID > 0 {
			return rec, false, true
		}
		return rec, false, false
	}
	if pid, e := strconv.Atoi(s); e == nil && pid > 0 {
		return watcherRecord{PID: pid}, true, true
	}
	return rec, false, false
}

func writeWatcherRecord(pidFile, projectDir, projectID string, pid int) error {
	rec := watcherRecord{PID: pid, ProjectDir: projectDir, ProjectID: projectID,
		StartedAt: time.Now().Format(time.RFC3339)}
	b, _ := json.Marshal(rec)
	return os.WriteFile(pidFile, b, 0644)
}

// isInsideGitRepo reports whether dir is inside a git working tree (walks up).
func isInsideGitRepo(dir string) bool {
	d, err := filepath.Abs(dir)
	if err != nil {
		return false
	}
	for {
		if fi, err := os.Stat(filepath.Join(d, ".git")); err == nil && (fi.IsDir() || fi.Mode().IsRegular()) {
			return true
		}
		parent := filepath.Dir(d)
		if parent == d {
			return false
		}
		d = parent
	}
}

// deriveProjectIDGo shells to the engine's single-source-of-truth
// derive_project_id() for `dir` (never reimplement it — same id hooks/MCP use).
func deriveProjectIDGo(sgRoot, dir string) string {
	out, err := runPython(sgRoot, fmt.Sprintf(
		"from memory import derive_project_id; print(derive_project_id(%q))", dir))
	if err != nil {
		return ""
	}
	return strings.TrimSpace(out)
}

// isWatcherAliveForProject verifies a LIVE watcher process exists AND its
// recorded project id matches cwd's — the fix for "already running" passing on
// stale/mismatched pid files (Task 2a). Used by `sg timeline`'s empty state and
// `sg doctor`.
func isWatcherAliveForProject(sgRoot, cwd string) bool {
	pidFile, _, _ := watcherPaths(sgRoot, cwd)
	rec, legacy, ok := readWatcherRecord(pidFile)
	if !ok || legacy || !isProcessAlive(rec.PID) {
		return false
	}
	want := deriveProjectIDGo(sgRoot, cwd)
	// If we can't derive (engine error), fall back to "process alive" rather
	// than falsely reporting dead.
	return want == "" || rec.ProjectID == "" || rec.ProjectID == want
}

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

// readPID returns just the pid from a watcher record (JSON or legacy bare int),
// for callers that only need liveness/stop and not the project fields.
func readPID(pidFile string) (int, bool) {
	rec, _, ok := readWatcherRecord(pidFile)
	if !ok {
		return 0, false
	}
	return rec.PID, true
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
	// Task 2b — never watch a non-repo (evidence: a watcher polled C:\Users\Asus
	// forever). Bail before any spawn; surface it, don't fake a green check.
	if !isInsideGitRepo(cwd) {
		if !quiet {
			fmt.Printf("  %s git watcher: skipped (not a git repo)\n",
				color.New(color.FgYellow).Sprint("○"))
		}
		return false, nil
	}

	pidFile, stopFile, logFile := watcherPaths(sgRoot, cwd)

	// Fast path: a LIVE watcher for THIS project already runs (Task 2a — verify
	// the process AND the project id, not just pid-file presence).
	if isWatcherAliveForProject(sgRoot, cwd) {
		return false, nil
	}

	lockFile := pidFile + ".lock"
	if err := os.MkdirAll(filepath.Dir(lockFile), 0755); err != nil {
		return false, err
	}
	clearStaleLock(lockFile)
	lf, lerr := os.OpenFile(lockFile, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if lerr != nil {
		return false, nil // another caller is handling this race window
	}
	lf.Close()
	defer os.Remove(lockFile)

	// Re-check under the lock.
	if isWatcherAliveForProject(sgRoot, cwd) {
		return false, nil
	}
	// Any record here is stale/dead/mismatched — log if it was a real record.
	if rec, legacy, ok := readWatcherRecord(pidFile); ok {
		who := rec.ProjectID
		if legacy || who == "" {
			who = "legacy record"
		}
		_watcherLog(logFile, fmt.Sprintf("stale watcher record for %s (pid %d dead/mismatched) — restarted", who, rec.PID))
	}
	os.Remove(pidFile)

	projectID := deriveProjectIDGo(sgRoot, cwd)

	// Task 2c — one watcher per project id: if some OTHER pid file already has a
	// live watcher for this same project id, don't spawn a duplicate.
	if other := liveWatcherForProjectID(sgRoot, projectID, pidFile); other != 0 {
		if !quiet {
			fmt.Printf("Watcher already running for this project (pid %d).\n", other)
		}
		return false, nil
	}

	enginePath := filepath.Join(sgRoot, "engine", "fs_watcher.py")
	pyArgs := []string{enginePath, cwd, filepath.Join(sgRoot, "engine"),
		"--pid-file", pidFile, "--stop-sentinel", stopFile}

	c, serr := spawnDetachedWatcher(pythonCmd(), pyArgs, logFile)
	if serr != nil {
		return false, serr
	}
	// JSON record (Task 2a) written immediately from the parent so no concurrent
	// caller sees "no pid file" right after the spawn; the child rewrites the
	// identical record shortly after.
	_ = writeWatcherRecord(pidFile, cwd, projectID, c.Process.Pid)

	if !quiet {
		fmt.Printf("Watcher started in background (pid %d). Logs: %s\n", c.Process.Pid, logFile)
		fmt.Println("Stop with: sg watch --stop")
	}
	return true, nil
}

// liveWatcherForProjectID scans db/watchers/*.pid for a LIVE watcher whose
// record's project_id matches, excluding `selfPidFile`. Returns its pid or 0.
func liveWatcherForProjectID(sgRoot, projectID, selfPidFile string) int {
	if projectID == "" {
		return 0
	}
	dir := filepath.Join(sgRoot, "db", "watchers")
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".pid") {
			continue
		}
		pf := filepath.Join(dir, e.Name())
		if pf == selfPidFile {
			continue
		}
		rec, legacy, ok := readWatcherRecord(pf)
		if ok && !legacy && rec.ProjectID == projectID && isProcessAlive(rec.PID) {
			return rec.PID
		}
	}
	return 0
}

// _watcherLog appends a single line to a watcher log file (best effort).
func _watcherLog(logFile, msg string) {
	if f, err := os.OpenFile(logFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644); err == nil {
		fmt.Fprintf(f, "[%s] [fs_watcher] %s\n", time.Now().Format("2006-01-02 15:04:05"), msg)
		f.Close()
	}
}

// reapStaleWatchers (Task 2d) cleans every pid file whose process is dead, whose
// project_dir no longer exists, or whose project_dir is no longer a git repo
// (covers deleted Temp scratchpads). Throttled to once/hour via db/kv. Also
// deletes zero-byte .log files older than 7 days.
func reapStaleWatchers(sgRoot string, force bool) {
	if !force && !reapDue(sgRoot) {
		return
	}
	dir := filepath.Join(sgRoot, "db", "watchers")
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for _, e := range entries {
		name := e.Name()
		full := filepath.Join(dir, name)
		if e.IsDir() {
			continue
		}
		if strings.HasSuffix(name, ".pid") {
			rec, legacy, ok := readWatcherRecord(full)
			dead := !ok || (!legacy && !isProcessAlive(rec.PID)) || (legacy && !isProcessAlive(rec.PID))
			badDir := !legacy && rec.ProjectDir != "" &&
				(!dirExists(rec.ProjectDir) || !isInsideGitRepo(rec.ProjectDir))
			if dead || badDir {
				if rec.PID > 0 && isProcessAlive(rec.PID) && badDir {
					killPID(rec.PID) // watching a gone/non-repo dir — stop it
				}
				os.Remove(full)
				_watcherLog(filepath.Join(dir, strings.TrimSuffix(name, ".pid")+".log"),
					fmt.Sprintf("reaped stale watcher record %s (dead=%v badDir=%v)", name, dead, badDir))
			}
			continue
		}
		if strings.HasSuffix(name, ".log") {
			if fi, err := e.Info(); err == nil && fi.Size() == 0 &&
				time.Since(fi.ModTime()) > 7*24*time.Hour {
				os.Remove(full)
			}
		}
	}
}

func dirExists(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.IsDir()
}

// reapDue throttles the reaper to once per hour via a timestamp in db/kv.
func reapDue(sgRoot string) bool {
	out, err := runPython(sgRoot,
		"from license import get_kv; print(get_kv('last_reap') or '')")
	if err == nil {
		if ts := strings.TrimSpace(out); ts != "" {
			if t, e := time.Parse(time.RFC3339, ts); e == nil && time.Since(t) < time.Hour {
				return false
			}
		}
	}
	_, _ = runPython(sgRoot, fmt.Sprintf(
		"from license import set_kv; set_kv('last_reap', %q)", time.Now().Format(time.RFC3339)))
	return true
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
