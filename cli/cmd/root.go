package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

// Version is the SkillGod CLI version. Setting Version makes Cobra register a
// `--version` flag automatically, so `sg --version` works. Override at build
// time with: go build -ldflags "-X skillgod/cmd.Version=<v>"
var Version = "1.0.0"

var rootCmd = &cobra.Command{
	Use:     "sg",
	Short:   "SkillGod — Claude Code on steroids",
	Long:    "SkillGod injects skills, memory and agents into any AI coding tool.",
	Version: Version,
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
}
