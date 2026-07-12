package cmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var initCmd = &cobra.Command{
	Use:   "init",
	Short: "Set up SkillGod in your environment",
	RunE:  runInit,
}

// repairMode: `sg init --repair` additionally audits local memory for rows left
// under the old (buggy) install-dir project key. A plain `sg init` re-run is
// already self-healing — it re-registers hooks idempotently and regenerates
// .mcp.json without the legacy SKILLGOD_PROJECT env — so the config fixes reach
// existing installs automatically; --repair only adds the (read-only) memory
// audit, which is opt-in because re-keying old rows is not safely automatable.
var repairMode bool

func init() {
	initCmd.Flags().BoolVar(&repairMode, "repair", false,
		"Also audit local memory for rows stranded under the pre-fix project key")
}

type MCPServer struct {
	Command string            `json:"command"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env"`
}

type MCPConfig struct {
	MCPServers map[string]MCPServer `json:"mcpServers"`
}

// IDE targets detected and configured by sg init
type ideTarget struct {
	name    string
	written bool
	note    string
}

func runInit(cmd *cobra.Command, args []string) error {
	green := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	cyan := color.New(color.FgCyan).SprintFunc()
	dim := color.New(color.Faint).SprintFunc()
	bold := color.New(color.Bold).SprintFunc()

	fmt.Println(bold("\nSkillGod init"))

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return fmt.Errorf("cannot find skillgod root: %w", err)
	}
	cwd, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("cannot resolve current directory: %w", err)
	}

	// ── Create vault directories (quietly) ─────────────────────────────────
	for _, d := range []string{
		filepath.Join(sgRoot, "vault", "instincts"),
		filepath.Join(sgRoot, "vault", "coding"),
		filepath.Join(sgRoot, "vault", "design"),
		filepath.Join(sgRoot, "vault", "writing"),
		filepath.Join(sgRoot, "vault", "devops"),
		filepath.Join(sgRoot, "vault", "security"),
		filepath.Join(sgRoot, "vault", "research"),
		filepath.Join(sgRoot, "vault", "agents"),
		filepath.Join(sgRoot, "vault", "meta"),
		filepath.Join(sgRoot, "db"),
	} {
		os.MkdirAll(d, 0755)
	}

	// ── Detect installed IDEs ──────────────────────────────────────────────
	detected := detectIDEs()
	if len(detected) > 0 {
		for _, d := range detected {
			fmt.Printf("  %s %s detected %s\n", green("✓"), d.name, dim("("+d.note+")"))
		}
	} else {
		fmt.Printf("  %s No IDE auto-detected — writing config to current dir\n", yellow("○"))
	}

	// Detect a stale .mcp.json (from before the project-id fix) BEFORE we
	// overwrite it, so we can tell the user why it changed.
	hadLegacyEnv := detectLegacyMCPEnv()

	// ── Write configs for all supported tools ──────────────────────────────
	enginePath := filepath.Join(sgRoot, "engine", "mcp_server.py")
	mcpConfig := MCPConfig{
		MCPServers: map[string]MCPServer{
			"skillgod": {
				Command: pythonCmd(),
				Args:    []string{enginePath},
				// BUG-B FIX — do NOT bake SKILLGOD_PROJECT here. It used to be
				// set to filepath.Base(sgRoot) (the ENGINE INSTALL dir name), a
				// machine-wide constant that made the MCP server key every
				// project's memory into one shared bucket. The server now derives
				// the project per call via derive_project_id() (git remote /
				// abspath), matching the hooks. SKILLGOD_ROOT stays — it's a
				// path hint, not a project key.
				Env: map[string]string{
					"SKILLGOD_ROOT": sgRoot,
				},
			},
		},
	}
	configBytes, _ := json.MarshalIndent(mcpConfig, "", "  ")
	writeIDEConfigs(sgRoot, configBytes, green, yellow)
	fmt.Printf("  %s .mcp.json written\n", green("✓"))

	if hadLegacyEnv {
		fmt.Printf("  %s Found outdated MCP configuration (fixed project-id bug).\n", green("✓"))
		fmt.Printf("     %s\n", dim("Regenerated .mcp.json without the legacy project env — restart your IDE to apply."))
	}

	// ── Register Claude Code lifecycle hooks (the automatic push path) ─────
	// Without this, nothing fires as the user types — the MCP tools exist but
	// are pull-only. This is what makes injection/capture automatic per prompt.
	if hookResults, herr := registerClaudeHooks(sgRoot); herr != nil {
		fmt.Printf("  %s could not register Claude Code hooks: %v\n", yellow("○"), herr)
	} else if len(hookResults) > 0 {
		fmt.Printf("  %s Registered SkillGod hooks in ~/.claude/settings.json:\n", green("✓"))
		for _, r := range hookResults {
			tag := green("(new)")
			if r.status == "skipped" {
				tag = dim("(already present, skipped)")
			}
			fmt.Printf("       %s %-18s %s\n", green("✓"), r.event, tag)
		}
	}

	// Cursor / Windsurf: no hooks equivalent, but each has its OWN confirmed
	// guaranteed-delivery mechanism (Cursor: .mdc alwaysApply; Windsurf:
	// trigger: always_on) — write the instruction there, and start the
	// filesystem/git watcher as a baseline capture layer independent of
	// either. This is real automation, just a different (weaker) guarantee
	// than Claude Code's hooks — see the "What's active" summary below for
	// the honest framing.
	hasCursor, hasWindsurf, hasClaudeCode, hasAntigravity := false, false, false, false
	for _, d := range detected {
		switch d.name {
		case "Cursor":
			hasCursor = true
		case "Windsurf":
			hasWindsurf = true
		case "Claude Code":
			hasClaudeCode = true
		case "Antigravity":
			hasAntigravity = true
		}
	}

	if hasAntigravity {
		if r, rerr := writeAntigravityRules(cwd); rerr != nil {
			fmt.Printf("  %s Antigravity: could not write rules file: %v\n", yellow("○"), rerr)
		} else {
			switch r.status {
			case "new":
				fmt.Printf("  %s Antigravity: wrote automatic-injection rule to %s (always_on)\n",
					green("✓"), dim(".agent/rules/skillgod.md"))
			case "skipped":
				fmt.Printf("  %s Antigravity: automatic-injection rule already present, skipped\n", green("✓"))
			case "foreign":
				fmt.Printf("  %s Antigravity: %s exists but wasn't written by sg init — left untouched\n",
					yellow("○"), dim(".agent/rules/skillgod.md"))
			}
		}
		// Antigravity reads a GLOBAL mcp_config.json, not the project-local
		// .mcp.json every other tool uses — without this it never sees the
		// MCP server at all, regardless of the rules file above.
		if status, merr := registerAntigravityMCP(mcpConfig.MCPServers["skillgod"]); merr != nil {
			fmt.Printf("  %s Antigravity: could not register MCP server: %v\n", yellow("○"), merr)
		} else {
			fmt.Printf("  %s Antigravity: MCP server registered in %s\n",
				green("✓"), dim("~/.gemini/config/mcp_config.json ("+status+")"))
		}
	}
	if hasCursor {
		if r, rerr := writeCursorRules(cwd); rerr != nil {
			fmt.Printf("  %s Cursor: could not write rules file: %v\n", yellow("○"), rerr)
		} else {
			switch r.status {
			case "new":
				fmt.Printf("  %s Cursor: wrote automatic-injection rule to %s (always applied)\n",
					green("✓"), dim(".cursor/rules/skillgod.mdc"))
			case "skipped":
				fmt.Printf("  %s Cursor: automatic-injection rule already present, skipped\n", green("✓"))
			case "foreign":
				fmt.Printf("  %s Cursor: %s exists but wasn't written by sg init — left untouched\n",
					yellow("○"), dim(".cursor/rules/skillgod.mdc"))
			}
		}
	}
	if hasWindsurf {
		// Writes BOTH .devin/rules/ (preferred by current Devin Desktop builds)
		// and .windsurf/rules/ (legacy, still read) — see writeWindsurfRules.
		if rs, rerr := writeWindsurfRules(cwd); rerr != nil {
			fmt.Printf("  %s Windsurf/Devin: could not write rules file: %v\n", yellow("○"), rerr)
		} else {
			for _, r := range rs {
				short := ".windsurf/rules/skillgod.md"
				label := "Windsurf (legacy)"
				if strings.Contains(r.path, ".devin") {
					short = ".devin/rules/skillgod.md"
					label = "Devin Desktop (preferred)"
				}
				switch r.status {
				case "new":
					fmt.Printf("  %s %s: wrote automatic-injection rule to %s (always_on)\n",
						green("✓"), label, dim(short))
				case "skipped":
					fmt.Printf("  %s %s: automatic-injection rule already present, skipped\n", green("✓"), label)
				case "foreign":
					fmt.Printf("  %s %s: %s exists but wasn't written by sg init — left untouched\n",
						yellow("○"), label, dim(short))
				}
			}
		}
	}

	watcherStarted := false
	if hasCursor || hasWindsurf || hasAntigravity {
		if started, werr := startProjectWatcher(sgRoot, cwd); werr != nil {
			fmt.Printf("  %s could not start filesystem/git watcher: %v\n", yellow("○"), werr)
		} else {
			watcherStarted = true // true whether newly started or already running — either way it's active
			if started {
				fmt.Printf("  %s Filesystem/git watcher active — captures decision-language commits automatically\n", green("✓"))
			} else {
				fmt.Printf("  %s Filesystem/git watcher already running for this project\n", green("✓"))
			}
		}
	}

	// ── Rebuild skill index (timed) ────────────────────────────────────────
	t0 := time.Now()
	indexOut, indexErr := runPython(sgRoot, "from skills import rebuild_index; n=rebuild_index(); print(n)")
	secs := time.Since(t0).Seconds()
	skillCount := strings.TrimSpace(indexOut)
	if indexErr != nil {
		fmt.Printf("  %s index skipped — run %s\n", yellow("○"), bold("sg stats"))
		skillCount = "0"
	} else {
		fmt.Printf("  %s %s skills indexed in %.1fs\n",
			green("✓"), green(skillCount), secs)
	}

	// ── Pro restore ─────────────────────────────────────────────────────────
	// A Pro user re-running init (or reinstalling) only has the free skills +
	// instincts on disk until the encrypted vault is decrypted again. If this
	// machine has a cached license key, re-run the sync path automatically so
	// init never leaves a paying user on the free vault; otherwise, when the
	// index looks free-tier-sized, tell them how to activate.
	cachedKey, _ := runPython(sgRoot,
		"from license import get_cached_key; print(get_cached_key())")
	cachedKey = strings.TrimSpace(cachedKey)
	if cachedKey != "" {
		fmt.Printf("  %s Pro license detected — restoring full vault...\n", green("✓"))
		licenseKey = cachedKey
		if err := runSync(cmd, []string{}); err == nil {
			if out, err := runPython(sgRoot,
				"from skills import rebuild_index; print(rebuild_index())"); err == nil {
				skillCount = strings.TrimSpace(out)
			}
		} else {
			fmt.Printf("  %s Pro restore failed — run %s manually\n",
				yellow("○"), bold("sg sync --key YOUR_KEY"))
		}
	} else {
		fmt.Printf("  %s Have Pro? Activate the full vault: %s\n",
			dim("○"), bold("sg sync --key YOUR_KEY"))
		fmt.Printf("     %s\n", dim("(your key is at app.skillgod.dev/dashboard/billing)"))
	}

	// ── Live preview: show skills firing for a real task ───────────────────
	demoTask := "build a React component"
	demoCode := fmt.Sprintf(
		`from skills import find_skills;`+
			`r=find_skills('%s', top_k=3);`+
			`[print(f"{x['score']:.2f}|{x['name']}|{' '.join(x.get('matched',[]))[:28]}") for x in r]`,
		demoTask,
	)
	if demoOut, err := runPython(sgRoot, demoCode); err == nil {
		var demoLines []string
		for _, line := range strings.Split(strings.TrimSpace(demoOut), "\n") {
			line = strings.TrimSpace(line)
			if line != "" {
				demoLines = append(demoLines, line)
			}
		}
		if len(demoLines) > 0 {
			fmt.Println()
			fmt.Printf("  %s  %s\n",
				bold("Preview:"),
				dim(fmt.Sprintf(`sg find "%s"`, demoTask)),
			)
			for _, line := range demoLines {
				parts := strings.SplitN(line, "|", 3)
				if len(parts) == 3 {
					fmt.Printf("    %-24s %s  %s\n",
						bold(parts[1]),
						green(parts[0]),
						cyan(parts[2]),
					)
				}
			}
			fmt.Printf("  %s\n", dim("These fire automatically before your AI sees your prompt."))
		}
	}

	// ── Next steps ──────────────────────────────────────────────────────────
	// Honesty requirement: Cursor/Windsurf must NOT be presented as equivalent
	// to Claude Code's hook-based automation. Each detected IDE gets its own
	// block stating its REAL mechanism and REAL guarantee level — a rules-file
	// instruction is guaranteed DELIVERED every prompt, but whether the model
	// ACTS on it every time is not the same guarantee hooks give.
	fmt.Println()
	fmt.Printf("  %s\n", bold("What's active:"))
	if skillCount != "0" && skillCount != "" {
		fmt.Printf("    %s  %s skills scored per task, top 3 injected\n", green("✓"), green(skillCount))
	}
	fmt.Printf("    %s  always-on instincts — no scoring needed\n", green("✓"))
	fmt.Printf("    %s  git-aware session memory (keyed per project)\n", green("✓"))

	if hasClaudeCode {
		fmt.Println()
		fmt.Printf("  %s\n", bold("Claude Code:"))
		fmt.Printf("    %s  MCP server (stdio) + automatic hooks — injection and memory\n", green("✓"))
		fmt.Printf("       capture fire on every prompt automatically, no action needed\n")
	}
	if hasCursor {
		fmt.Println()
		fmt.Printf("  %s\n", bold("Cursor:"))
		fmt.Printf("    %s  Automatic-injection rule installed (always applied by Cursor)\n", green("✓"))
		fmt.Printf("       %s\n", dim("— the instruction is guaranteed to reach the model every"))
		fmt.Printf("       %s\n", dim("prompt; whether the model acts on it every time is not"))
		fmt.Printf("       %s\n", dim("guaranteed the way Claude Code's hooks are."))
		if watcherStarted {
			fmt.Printf("    %s  Filesystem watcher active — captures decision-language commits\n", green("✓"))
			fmt.Printf("       automatically, independent of the AI conversation. Self-healing:\n")
			fmt.Printf("       %s\n", dim("if it's ever killed (e.g. across a machine reboot), it restarts"))
			fmt.Printf("       %s\n", dim("automatically the next time you use SkillGod in this project —"))
			fmt.Printf("       %s\n", dim("no need to run sg init or sg watch again. The one honest caveat:"))
			fmt.Printf("       %s\n", dim("a long idle stretch with zero SkillGod usage after a reboot"))
			fmt.Printf("       %s\n", dim("leaves it off until that next real interaction, not restarted"))
			fmt.Printf("       %s\n", dim("proactively on boot itself."))
		}
		fmt.Printf("    %s  Full hook-based automatic injection (Claude Code only,\n", yellow("○"))
		fmt.Printf("       not yet available on Cursor)\n")
	}
	if hasWindsurf {
		fmt.Println()
		fmt.Printf("  %s\n", bold("Windsurf:"))
		fmt.Printf("    %s  Automatic-injection rule installed (always_on)\n", green("✓"))
		fmt.Printf("       %s\n", dim("— the instruction is guaranteed to reach the model every"))
		fmt.Printf("       %s\n", dim("prompt; whether the model acts on it every time is not"))
		fmt.Printf("       %s\n", dim("guaranteed the way Claude Code's hooks are."))
		if watcherStarted {
			fmt.Printf("    %s  Filesystem watcher active — captures decision-language commits\n", green("✓"))
			fmt.Printf("       automatically, independent of the AI conversation\n")
		}
		fmt.Printf("    %s  Full hook-based automatic injection (Claude Code only,\n", yellow("○"))
		fmt.Printf("       not yet available on Windsurf)\n")
	}
	if hasAntigravity {
		fmt.Println()
		fmt.Printf("  %s\n", bold("Antigravity:"))
		fmt.Printf("    %s  Automatic-injection rule installed (always_on)\n", green("✓"))
		fmt.Printf("       %s\n", dim("— the instruction is guaranteed to reach the model every"))
		fmt.Printf("       %s\n", dim("prompt; whether the model acts on it every time is not"))
		fmt.Printf("       %s\n", dim("guaranteed the way Claude Code's hooks are."))
		fmt.Printf("    %s  MCP server registered globally — required for Antigravity to\n", green("✓"))
		fmt.Printf("       %s\n", dim("see the sg_inject_context / sg_save_memory tools at all"))
		if watcherStarted {
			fmt.Printf("    %s  Filesystem watcher active — captures decision-language commits\n", green("✓"))
			fmt.Printf("       automatically, independent of the AI conversation\n")
		}
		fmt.Printf("    %s  This integration is newer and less battle-tested than Cursor/\n", yellow("○"))
		fmt.Printf("       Windsurf's — if skills don't seem to be firing, run\n")
		fmt.Printf("       %s and check %s\n", bold("sg find \"<task>\""), dim(".agent/rules/skillgod.md"))
		fmt.Printf("    %s  Full hook-based automatic injection (Claude Code only,\n", yellow("○"))
		fmt.Printf("       not yet available on Antigravity)\n")
	}

	// ── Repair mode: audit memory for rows stranded under the old key ───────
	if repairMode {
		auditMemoryKeys(sgRoot, green, yellow, dim)
	}

	// ── Anonymous install ping + optional account link ─────────────────────
	// The ping carries only the anonymous install_id (a random UUID minted
	// locally, never derived from hardware), OS and detected IDE — no email,
	// no login, no prompt. Linking an email is a separate, voluntary browser
	// action via the printed URL; the CLI never asks for credentials.
	installID, _ := runPython(sgRoot,
		"from license import get_install_id; print(get_install_id())")
	installID = strings.TrimSpace(installID)
	if installID != "" {
		ideName := ""
		if len(detected) > 0 {
			ideName = detected[0].name
		}
		sendInitPing(installID, ideName)
		fmt.Println()
		fmt.Printf("  %s\n", bold("SkillGod is ready."))
		fmt.Printf("    To activate Pro, redeem a code:   %s\n", bold("sg redeem YOUR-CODE"))
		fmt.Printf("    Or link your account %s for updates and\n", dim("(optional)"))
		fmt.Printf("    license management:\n")
		fmt.Printf("      %s\n", cyan(appBaseURL()+"/link?install="+installID))
	}

	fmt.Println()
	target := "your IDE"
	if len(detected) > 0 {
		target = detected[0].name
	}
	fmt.Printf("Restart %s to activate.\n\n", cyan(target))
	fmt.Printf("  %s  see what fires for your task\n", bold("sg find \"<your task>\""))
	fmt.Printf("  %s      memory timeline for this project\n", bold("sg timeline"))
	fmt.Printf("  %s         vault health + usage stats\n", bold("sg stats"))
	fmt.Println()
	return nil
}

// detectLegacyMCPEnv reports whether an existing .mcp.json (current dir or the
// global ~/.claude/.mcp.json) still carries the pre-fix SKILLGOD_PROJECT env —
// the machine-wide constant that mis-keyed MCP memory. Used only to explain to
// the user why their config was regenerated.
func detectLegacyMCPEnv() bool {
	cwd, _ := os.Getwd()
	home, _ := os.UserHomeDir()
	candidates := []string{
		filepath.Join(cwd, ".mcp.json"),
		filepath.Join(home, ".claude", ".mcp.json"),
	}
	for _, p := range candidates {
		if data, err := os.ReadFile(p); err == nil {
			if strings.Contains(string(data), "SKILLGOD_PROJECT") {
				return true
			}
		}
	}
	return false
}

// auditMemoryKeys (sg init --repair) counts memory rows stranded under the old
// install-dir project key. Read-only: re-keying is NOT auto-executed because the
// original project each row belonged to was never recorded — the bug collapsed
// multiple projects into one key, so the mapping back is unrecoverable.
// auditMemoryKeys (sg init --repair) classifies every distinct `project` value
// in local memory against the shape derive_project_id() actually produces, and
// reports every row keyed outside that shape — not just rows under THIS
// machine's current install-dir constant. derive_project_id() (engine/memory.py)
// has exactly two output forms:
//  1. git remote present:  normalised host/owner/repo, e.g. "github-com-owner-repo"
//     (no fixed prefix is guaranteed — depends on the remote's actual host)
//  2. no remote:            "<sanitised-folder-name>-<8 lowercase hex chars>"
//     (sha256(abspath)[:8] — this suffix IS a reliable, checkable fingerprint)
//
// Form 2 is unambiguous (an 8-hex-char suffix essentially never appears at the
// end of a hand-typed or install-dir-derived string by chance). Form 1 has no
// such fingerprint in general, so it's matched heuristically against common
// normalised host fragments (-com-, -org-, -io-, etc.) — this will not catch
// every possible self-hosted git remote, and is documented as best-effort
// detection, same as the rest of this audit: broader coverage, same
// conservative no-auto-reattribution behaviour.
func auditMemoryKeys(sgRoot string, green, yellow, dim func(...interface{}) string) {
	code := `
import re
from memory import get_db
c = get_db()  # ensures the memory table exists (executescript'd schema) —
              # a truly fresh install (session_start.py never run) otherwise
              # has no 'memory' table at all and a raw sqlite3.connect() query
              # against it raises "no such table: memory".
rows = c.execute("SELECT project, COUNT(*) FROM memory GROUP BY project ORDER BY project").fetchall()
HASH_SUFFIX = re.compile(r'^.+-[0-9a-f]{8}$')       # derive_project_id() no-remote form
HOST_LIKE   = re.compile(r'-(com|org|net|io|dev|co|ht|sh)-')  # derive_project_id() git-remote form (heuristic)
def conforms(k):
    return bool(HASH_SUFFIX.match(k)) or bool(HOST_LIKE.search(k))
for k, n in rows:
    if not conforms(k):
        print(f"{k}\t{n}")
`
	out, err := runPython(sgRoot, code)
	fmt.Println()
	fmt.Printf("  %s\n", dim("Memory key audit (--repair):"))
	if err != nil {
		fmt.Printf("    %s could not read local memory DB: %v\n", yellow("○"), err)
		return
	}

	type strandedKey struct {
		key   string
		count int
	}
	var stranded []strandedKey
	total := 0
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.SplitN(line, "\t", 2)
		if len(parts) != 2 {
			continue
		}
		n := 0
		fmt.Sscanf(parts[1], "%d", &n)
		stranded = append(stranded, strandedKey{parts[0], n})
		total += n
	}

	if len(stranded) == 0 {
		fmt.Printf("    %s No stranded memory found — all rows use current project-id format.\n", green("✓"))
		return
	}

	fmt.Printf("    %s %d memory row(s) found under keys that don't match the\n", yellow("⚠"), total)
	fmt.Printf("       current project-id format. These may be stranded from\n")
	fmt.Printf("       old installs, moved directories, or renamed folders:\n")
	fmt.Println()
	for _, s := range stranded {
		rowWord := "row"
		if s.count != 1 {
			rowWord = "rows"
		}
		fmt.Printf("         %-28q — %d %s\n", s.key, s.count, rowWord)
	}
	fmt.Println()
	fmt.Printf("       %s\n", dim("These are left in place (not deleted). They cannot be"))
	fmt.Printf("       %s\n", dim("reliably reassigned to a specific project — the bug"))
	fmt.Printf("       %s\n", dim("never recorded which project each row belonged to."))
	fmt.Printf("       %s\n", dim("New memory from here on is keyed correctly per project."))
}

// detectIDEs returns the IDEs/tools actually present on this machine.
func detectIDEs() []ideTarget {
	home, _ := os.UserHomeDir()
	cwd, _ := os.Getwd()

	short := func(p string) string {
		if home != "" && strings.HasPrefix(p, home) {
			return "~" + p[len(home):]
		}
		return p
	}

	checks := []struct{ name, path string }{
		{"Cursor", filepath.Join(home, ".cursor")},
		{"Claude Code", filepath.Join(home, ".claude")},
		{"Windsurf", filepath.Join(home, ".codeium", "windsurf")},
		{"Antigravity", filepath.Join(home, ".antigravity")},
		{"Continue (Ollama)", filepath.Join(home, ".continue")},
		{"VS Code", filepath.Join(cwd, ".vscode")},
	}

	var found []ideTarget
	for _, c := range checks {
		if c.path == "" {
			continue
		}
		if _, err := os.Stat(c.path); err == nil {
			found = append(found, ideTarget{name: c.name, written: true, note: short(c.path)})
		}
	}
	return found
}

// writeIDEConfigs writes config files for every supported IDE/tool.
// Returns a slice of targets with written status and notes.
func writeIDEConfigs(sgRoot string, mcpBytes []byte, green, yellow func(...interface{}) string) []ideTarget {
	var targets []ideTarget
	home, _ := os.UserHomeDir()
	cwd, _ := os.Getwd()

	// ── 1. .mcp.json (Claude Code, Cursor, Antigravity, Windsurf) ──────────
	cwdMCP := filepath.Join(cwd, ".mcp.json")
	err := os.WriteFile(cwdMCP, mcpBytes, 0644)
	targets = append(targets, ideTarget{
		name:    "Claude Code",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})
	targets = append(targets, ideTarget{
		name:    "Cursor",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})
	targets = append(targets, ideTarget{
		name:    "Antigravity",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})
	targets = append(targets, ideTarget{
		name:    "Windsurf",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})

	// Also write to ~/.claude/.mcp.json for global Claude Code
	claudeDir := filepath.Join(home, ".claude")
	os.MkdirAll(claudeDir, 0755)
	os.WriteFile(filepath.Join(claudeDir, ".mcp.json"), mcpBytes, 0644)

	// ── 2. GitHub Copilot (.github/copilot-instructions.md) ─────────────────
	// GitHub Copilot reads this file and injects it into every session.
	// Works in VS Code, JetBrains, Neovim, vim with Copilot plugin.
	githubDir := filepath.Join(cwd, ".github")
	os.MkdirAll(githubDir, 0755)
	copilotInstructions := buildCopilotInstructions(sgRoot)
	copilotPath := filepath.Join(githubDir, "copilot-instructions.md")
	copilotErr := os.WriteFile(copilotPath, []byte(copilotInstructions), 0644)
	targets = append(targets, ideTarget{
		name:    "GitHub Copilot",
		written: copilotErr == nil,
		note:    ".github/copilot-instructions.md",
	})

	// ── 3. Ollama / Continue.dev (~/.continue/config.json) ──────────────────
	// Continue.dev is the most popular Ollama IDE integration.
	// It reads ~/.continue/config.json and supports custom system prompts.
	continueDir := filepath.Join(home, ".continue")
	os.MkdirAll(continueDir, 0755)
	continueConfigPath := filepath.Join(continueDir, "config.json")
	continueErr := writeContinueConfig(sgRoot, continueConfigPath)
	targets = append(targets, ideTarget{
		name:    "Ollama (Continue)",
		written: continueErr == nil,
		note:    "~/.continue/config.json",
	})

	// ── 4. VS Code settings (Codex / GitHub Copilot workspace settings) ─────
	vscodeDir := filepath.Join(cwd, ".vscode")
	if _, err := os.Stat(vscodeDir); err == nil {
		// .vscode exists — write workspace settings to enable Copilot instructions
		settingsPath := filepath.Join(vscodeDir, "settings.json")
		vsErr := writeVSCodeSettings(settingsPath)
		targets = append(targets, ideTarget{
			name:    "VS Code (Codex)",
			written: vsErr == nil,
			note:    ".vscode/settings.json updated",
		})
	} else {
		targets = append(targets, ideTarget{
			name:    "VS Code (Codex)",
			written: false,
			note:    "no .vscode/ found — open in VS Code first",
		})
	}

	return targets
}

// buildCopilotInstructions returns the content for .github/copilot-instructions.md
func buildCopilotInstructions(sgRoot string) string {
	return `# SkillGod — Active Coding Standards

> Auto-generated by SkillGod (sg init). Do not edit manually — run sg init to regenerate.

## What SkillGod Does

SkillGod injects 1,927 curated skills and project memory into every AI coding session.
These instructions are the static fallback for GitHub Copilot (which does not support MCP).
For full live injection, use Claude Code or Cursor with sg init.

## Core Rules (always apply)

- Always verify output matches the request before saying done
- Never modify files in vault/ directly — use sg learn or vault/meta/
- Validate inputs before any database write
- Use absolute imports, not relative
- Check error returns — never silently ignore them
- Write tests for anything that could break in production

## Memory

Project decisions, patterns, and errors are stored by SkillGod memory.
Key decisions from previous sessions will be injected at session start when using a supported IDE.

## Skill Vault

This project has access to 1,927 curated skills across:
- coding/ — Python, TypeScript, React, debugging, code review
- design/ — UI/UX, layout, Figma, brutalist patterns
- devops/ — Docker, Railway, Vercel, CI/CD
- security/ — OWASP, injection detection, auth patterns
- agents/ — multi-agent orchestration, MCP, swarm patterns
- writing/ — docs, README, blog, API documentation

Run ` + "`sg find <task>`" + ` to see which skills apply to your current task.
Run ` + "`sg stats`" + ` to see vault health and memory stats.
`
}

// writeContinueConfig writes or merges SkillGod config into ~/.continue/config.json
func writeContinueConfig(sgRoot, configPath string) error {
	// Read existing config if present
	existing := map[string]interface{}{}
	if data, err := os.ReadFile(configPath); err == nil {
		json.Unmarshal(data, &existing)
	}

	// SkillGod system message for Ollama sessions
	systemMsg := `You are working with SkillGod active. SkillGod provides:
- 1,927 curated coding skills injected based on task relevance
- Persistent memory of project decisions, patterns, and errors
- Security scanning on all inputs

Core rules:
- Always verify output matches the request before saying done
- Validate inputs before database writes
- Use absolute imports
- Never silently ignore errors

Run sg find <task> in terminal to see relevant skills for your current task.
Run sg stats to check vault and memory status.`

	existing["systemMessage"] = systemMsg

	// Ensure tabAutocompleteModel is set if not already configured
	if _, ok := existing["tabAutocompleteModel"]; !ok {
		existing["tabAutocompleteModel"] = nil
	}

	// Tag with SkillGod version marker
	existing["_skillgod"] = map[string]string{
		"managed_by": "sg init",
		"version":    "1.0.0",
	}

	out, err := json.MarshalIndent(existing, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(configPath, out, 0644)
}

// writeVSCodeSettings enables Copilot workspace-level instructions in VS Code
func writeVSCodeSettings(settingsPath string) error {
	existing := map[string]interface{}{}
	if data, err := os.ReadFile(settingsPath); err == nil {
		json.Unmarshal(data, &existing)
	}

	// Enable GitHub Copilot to use .github/copilot-instructions.md
	existing["github.copilot.chat.codeGeneration.useInstructionFiles"] = true
	existing["github.copilot.chat.reviewSelection.useInstructionFiles"] = true

	out, err := json.MarshalIndent(existing, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(settingsPath, out, 0644)
}

// isSkillGodRoot reports whether dir contains the SkillGod engine.
func isSkillGodRoot(dir string) bool {
	_, err := os.Stat(filepath.Join(dir, "engine", "mcp_server.py"))
	return err == nil
}

// findSkillGodRoot locates the installed engine + vault. For users who
// installed via the one-line installer, this lives in ~/.skillgod (the
// installer unpacks the engine bundle there). Developers running from a
// source checkout resolve to the repo via the cwd / parent-walk checks.
func findSkillGodRoot() (string, error) {
	// 1. Explicit override — highest priority.
	if env := os.Getenv("SKILLGOD_HOME"); env != "" && isSkillGodRoot(env) {
		return env, nil
	}

	// 2. Current dir (developer running inside the source repo).
	if isSkillGodRoot(".") {
		abs, _ := filepath.Abs(".")
		return abs, nil
	}

	// 3. Installed location — ~/.skillgod (the installer's target).
	if home, err := os.UserHomeDir(); err == nil {
		root := filepath.Join(home, ".skillgod")
		if isSkillGodRoot(root) {
			return root, nil
		}
	}

	// 4. Next to the binary, then walk up its parents.
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		for d := dir; d != filepath.Dir(d); d = filepath.Dir(d) {
			if isSkillGodRoot(d) {
				return d, nil
			}
		}
	}

	return "", fmt.Errorf("SkillGod engine not found in ~/.skillgod — reinstall from https://skillgod.dev/download, or set SKILLGOD_HOME to your engine directory")
}

// hookResult reports what happened to one event during hook registration.
type hookResult struct {
	event  string
	status string // "new" | "skipped"
}

// claudeHookEvents maps each Claude Code lifecycle event to its SkillGod script.
// All five lifecycle hooks now ship real scripts and are registered here;
// SessionEnd (session_end.py) summarizes the session into SQLite on close.
var claudeHookEvents = []struct{ event, script string }{
	{"SessionStart", "session_start.py"},
	{"UserPromptSubmit", "user_prompt_submit.py"},
	{"PreToolUse", "pre_tool.py"},
	{"PostToolUse", "post_tool.py"},
	{"SessionEnd", "session_end.py"},
}

// registerClaudeHooks merges SkillGod's five lifecycle hooks into
// ~/.claude/settings.json. It preserves every existing top-level key and every
// non-SkillGod hook entry, is idempotent (re-runs add nothing), and writes
// atomically (temp file + rename) so a crash mid-write can't corrupt settings.
func registerClaudeHooks(sgRoot string) ([]hookResult, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}
	claudeDir := filepath.Join(home, ".claude")
	if err := os.MkdirAll(claudeDir, 0755); err != nil {
		return nil, err
	}
	settingsPath := filepath.Join(claudeDir, "settings.json")

	// Read + parse into a generic map so unknown keys survive round-tripping.
	root := map[string]interface{}{}
	var raw []byte
	if data, rerr := os.ReadFile(settingsPath); rerr == nil {
		raw = data
		if len(strings.TrimSpace(string(data))) > 0 {
			if json.Unmarshal(data, &root) != nil {
				// Invalid JSON — never overwrite blindly. Back up, warn, restart.
				backup := settingsPath + ".skillgod-backup-" + time.Now().Format("20060102-150405")
				os.WriteFile(backup, data, 0644)
				fmt.Printf("  ⚠ existing settings.json was not valid JSON — backed up to %s and starting a fresh hooks section\n", backup)
				root = map[string]interface{}{}
				raw = nil
			}
		}
	}

	// hooks must be an object. If it exists as another type, back up + reset it
	// (other top-level keys are still preserved).
	hooksObj, ok := root["hooks"].(map[string]interface{})
	if !ok {
		if _, exists := root["hooks"]; exists && raw != nil {
			backup := settingsPath + ".skillgod-backup-" + time.Now().Format("20060102-150405")
			os.WriteFile(backup, raw, 0644)
			fmt.Printf("  ⚠ existing 'hooks' was not an object — backed up to %s, replacing just the hooks section (other settings preserved)\n", backup)
		}
		hooksObj = map[string]interface{}{}
	}

	var results []hookResult
	for _, e := range claudeHookEvents {
		scriptPath := filepath.Join(sgRoot, "hooks", e.script)
		cmdStr := fmt.Sprintf(`%s "%s"`, pythonCmd(), scriptPath)

		arr, _ := hooksObj[e.event].([]interface{})
		if hookAlreadyRegistered(arr, e.script) {
			results = append(results, hookResult{e.event, "skipped"})
			continue
		}
		group := map[string]interface{}{
			"hooks": []interface{}{
				map[string]interface{}{"type": "command", "command": cmdStr},
			},
		}
		hooksObj[e.event] = append(arr, group)
		results = append(results, hookResult{e.event, "new"})
	}
	root["hooks"] = hooksObj

	out, merr := json.MarshalIndent(root, "", "  ")
	if merr != nil {
		return results, merr
	}
	// Atomic write: temp file then rename, so a crash never truncates settings.
	tmp := settingsPath + ".tmp"
	if werr := os.WriteFile(tmp, out, 0644); werr != nil {
		return results, werr
	}
	if rerr := os.Rename(tmp, settingsPath); rerr != nil {
		os.Remove(tmp)
		return results, rerr
	}
	return results, nil
}

// registerAntigravityMCP merges the skillgod entry into Antigravity's MCP
// config. UNLIKE Claude Code / Cursor / Windsurf, Antigravity does NOT read
// a project-local .mcp.json — its docs (antigravity.google/docs, Google
// Codelabs, and multiple independent developer write-ups converging on the
// same path as of July 2026) describe a single GLOBAL config at
// ~/.gemini/config/mcp_config.json shared across the Antigravity IDE and
// CLI. Writing only .mcp.json (as every other supported tool needs) would
// leave Antigravity never seeing the MCP server at all. Same non-clobber
// discipline as registerClaudeHooks: read-merge-write, unknown keys and
// other configured servers survive, only our own "skillgod" entry is ours
// to overwrite on every run.
//
// CONFIDENCE NOTE: this path/schema could not be verified against a running
// Antigravity install the way Claude Code's hooks were — antigravity.google
// is a JS-rendered SPA that returned no fetchable text content. If this
// turns out to be wrong, the fix is isolated to this one function.
func registerAntigravityMCP(server MCPServer) (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	configDir := filepath.Join(home, ".gemini", "config")
	if err := os.MkdirAll(configDir, 0755); err != nil {
		return "", err
	}
	configPath := filepath.Join(configDir, "mcp_config.json")

	root := map[string]interface{}{}
	if data, rerr := os.ReadFile(configPath); rerr == nil {
		if len(strings.TrimSpace(string(data))) > 0 {
			if json.Unmarshal(data, &root) != nil {
				backup := configPath + ".skillgod-backup-" + time.Now().Format("20060102-150405")
				os.WriteFile(backup, data, 0644)
				fmt.Printf("  ⚠ existing mcp_config.json was not valid JSON — backed up to %s and starting fresh\n", backup)
				root = map[string]interface{}{}
			}
		}
	}

	serversObj, ok := root["mcpServers"].(map[string]interface{})
	if !ok {
		serversObj = map[string]interface{}{}
	}
	_, existed := serversObj["skillgod"]
	serversObj["skillgod"] = map[string]interface{}{
		"command": server.Command,
		"args":    server.Args,
		"env":     server.Env,
	}
	root["mcpServers"] = serversObj

	out, merr := json.MarshalIndent(root, "", "  ")
	if merr != nil {
		return "", merr
	}
	tmp := configPath + ".tmp"
	if werr := os.WriteFile(tmp, out, 0644); werr != nil {
		return "", werr
	}
	if rerr := os.Rename(tmp, configPath); rerr != nil {
		os.Remove(tmp)
		return "", rerr
	}
	if existed {
		return "updated", nil
	}
	return "new", nil
}

// hookAlreadyRegistered reports whether any group in an event's array already
// invokes the given SkillGod script. Matches on the script basename so it stays
// idempotent regardless of how the absolute path was formatted (slash style,
// quoting) by a prior run.
func hookAlreadyRegistered(arr []interface{}, scriptBase string) bool {
	for _, g := range arr {
		gm, ok := g.(map[string]interface{})
		if !ok {
			continue
		}
		hs, ok := gm["hooks"].([]interface{})
		if !ok {
			continue
		}
		for _, h := range hs {
			hm, ok := h.(map[string]interface{})
			if !ok {
				continue
			}
			if cmd, _ := hm["command"].(string); strings.Contains(cmd, scriptBase) {
				return true
			}
		}
	}
	return false
}

// appBaseURL is the dashboard origin for the optional account-link URL.
// Overridable for local/test backends the same way SKILLGOD_API is.
func appBaseURL() string {
	if v := os.Getenv("SKILLGOD_APP"); v != "" {
		return strings.TrimRight(v, "/")
	}
	return "https://app.skillgod.dev"
}

// sendInitPing fires the anonymous install/init telemetry event: install_id
// (random local UUID), OS, and the detected IDE. No email, no hostname, no
// hardware identifiers. Fire-and-forget: short timeout, silent on any
// failure, and skipped entirely when SKILLGOD_NO_TELEMETRY is set.
func sendInitPing(installID, ide string) {
	if os.Getenv("SKILLGOD_NO_TELEMETRY") != "" {
		return
	}
	apiURL := os.Getenv("SKILLGOD_API")
	if apiURL == "" {
		apiURL = "https://api.skillgod.dev"
	}
	payload, err := json.Marshal(map[string]interface{}{
		"event":      "init",
		"machine_id": installID, // anonymous install id, not a hardware id
		"plan":       "free",
		"metadata": map[string]string{
			"os":         runtime.GOOS,
			"ide":        ide,
			"install_id": installID,
		},
	})
	if err != nil {
		return
	}
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Post(
		strings.TrimRight(apiURL, "/")+"/v1/track",
		"application/json", bytes.NewReader(payload))
	if err == nil {
		resp.Body.Close()
	}
}

func pythonCmd() string {
	if runtime.GOOS == "windows" {
		return "python"
	}
	return "python3"
}

func runPython(root, code string) (string, error) {
	engineDir := filepath.Join(root, "engine")
	c := exec.Command(pythonCmd(),
		"-c",
		fmt.Sprintf("import sys; sys.path.insert(0,r'%s'); %s", engineDir, code),
	)
	c.Dir = root
	out, err := c.Output()
	if err != nil {
		// BUG FIX — exec.Cmd.Output() already captures the child's stderr
		// into ExitError.Stderr (since c.Stderr was left nil); the old code
		// just returned the raw err, whose Error() string is a bare
		// "exit status 1" with no trace of the real Python failure. Every
		// caller of runPython() that wraps this error (sg signals, sg
		// promote, etc.) was therefore always showing a useless message —
		// the actual SyntaxError/traceback that would have revealed the
		// last two real bugs immediately was being thrown away right here.
		if exitErr, ok := err.(*exec.ExitError); ok && len(exitErr.Stderr) > 0 {
			return "", fmt.Errorf("%w\n%s", err, strings.TrimRight(string(exitErr.Stderr), "\n"))
		}
		return "", err
	}
	return string(out), nil
}
