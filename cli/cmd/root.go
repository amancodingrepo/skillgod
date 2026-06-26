package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "sg",
	Short: "SkillGod — Claude Code on steroids",
	Long:  "SkillGod injects skills, memory and agents into any AI coding tool.",
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
