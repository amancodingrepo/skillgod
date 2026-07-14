package cmd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

// Version is the SkillGod CLI version. Setting Version makes Cobra register a
// `--version` flag automatically, so `sg --version` works. Override at build
// time with: go build -ldflags "-X skillgod/cmd.Version=<v>"
var Version = "1.0.1"

// engineVersion reads ~/.skillgod/VERSION (written into engine.zip by
// build_engine_bundle.py). Returns ("", false) when the file is absent — i.e.
// a pre-1.0.1 engine that predates version stamping (Task 4).
func engineVersion() (string, bool) {
	root, err := findSkillGodRoot()
	if err != nil {
		return "", false
	}
	data, err := os.ReadFile(filepath.Join(root, "VERSION"))
	if err != nil {
		return "", false
	}
	return strings.TrimSpace(string(data)), true
}

// versionBase strips a leading "v" and a "+<sha>" build-metadata suffix so
// "v1.0.1", "1.0.1", and "1.0.1+abc123" all compare equal for drift detection.
func versionBase(v string) string {
	v = strings.TrimSpace(v)
	v = strings.TrimPrefix(v, "v")
	v = strings.TrimPrefix(v, "V")
	if i := strings.IndexByte(v, '+'); i >= 0 {
		v = v[:i]
	}
	return strings.TrimSpace(v)
}

// engineDrift reports (mismatched, engineDisplay). mismatched is true when the
// installed engine's base version differs from the binary's (or is missing).
func engineDrift() (bool, string) {
	ev, ok := engineVersion()
	if !ok {
		return true, "UNKNOWN (pre-1.0.1 — run sg update)"
	}
	return versionBase(ev) != versionBase(Version), ev
}

var rootCmd = &cobra.Command{
	Use:     "sg",
	Short:   "SkillGod — Claude Code on steroids",
	Long:    "SkillGod injects skills, memory and agents into any AI coding tool.",
	Version: Version,
	// Self-healing watcher startup: every `sg` command opportunistically
	// checks whether this project's filesystem/git watcher is alive and
	// restarts it if not (dead across a reboot, or never started). This is
	// the CLI-side leg of the same check wired into hooks/session_start.py,
	// hooks/pre_tool.py, and engine/mcp_server.py — so the watcher repairs
	// itself the next time the user does ANYTHING that touches SkillGod,
	// with no OS-level autostart (systemd/launchd/registry) required.
	// Excluded: `init` and `watch` manage the watcher explicitly themselves;
	// running this ahead of them would just be redundant work on every
	// invocation of the two commands that already handle it deliberately.
	PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
		if cmd.Name() != "init" && cmd.Name() != "watch" && cmd.Name() != "doctor" {
			// Task 2d — opportunistic reaper (throttled to once/hour via db/kv).
			if root, err := findSkillGodRoot(); err == nil {
				reapStaleWatchers(root, false)
			}
			selfHealWatcher()
			// Task 4 — warn (don't block) on engine/binary version drift.
			if mismatched, ev := engineDrift(); mismatched {
				fmt.Fprintf(os.Stderr, "%s engine %s does not match sg %s — run sg update\n",
					color.New(color.FgYellow).Sprint("⚠"), ev, Version)
			}
		}
		return nil
	},
}

func Execute() {
	// Task 4 — sg --version shows BOTH the binary and the installed engine
	// version: "sg 1.0.1 (engine 1.0.1+abc1234)".
	ev, ok := engineVersion()
	if !ok {
		ev = "UNKNOWN (pre-1.0.1 — run sg update)"
	}
	rootCmd.Version = fmt.Sprintf("%s (engine %s)", Version, ev)
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func init() {
	rootCmd.AddCommand(initCmd)
	rootCmd.AddCommand(runCmd)
	rootCmd.AddCommand(findCmd)
	rootCmd.AddCommand(learnCmd)
	rootCmd.AddCommand(syncCmd)
	rootCmd.AddCommand(statsCmd)
	rootCmd.AddCommand(scanCmd)
	rootCmd.AddCommand(buildCmd)
	rootCmd.AddCommand(signalsCmd)
	rootCmd.AddCommand(promoteCmd)
	rootCmd.AddCommand(updateCmd)
	rootCmd.AddCommand(watchCmd)
}
