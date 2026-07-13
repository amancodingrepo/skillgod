package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

// Version is the SkillGod CLI version. Setting Version makes Cobra register a
// `--version` flag automatically, so `sg --version` works. Override at build
// time with: go build -ldflags "-X skillgod/cmd.Version=<v>"
var Version = "1.0.1"

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
		if cmd.Name() != "init" && cmd.Name() != "watch" {
			selfHealWatcher()
		}
		return nil
	},
}

func Execute() {
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
