package cmd

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"
)

var runCmd = &cobra.Command{
	Use:   "run [tool] [args...]",
	Short: "Run any AI tool with SkillGod skills injected",
	Long: `Wraps any AI coding tool with automatic skill injection.

Examples:
  sg run claude        Start Claude Code with skills active
  sg run cursor .      Open Cursor with skills active
  sg run aider         Start Aider with skills active`,
	Args: cobra.MinimumNArgs(1),
	RunE: runRun,
}

func runRun(cmd *cobra.Command, args []string) error {
	tool     := args[0]
	toolArgs := args[1:]

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	env := append(os.Environ(),
		fmt.Sprintf("SKILLGOD_ROOT=%s", sgRoot),
		"SKILLGOD_ACTIVE=1",
	)

	toolBin, err := exec.LookPath(tool)
	if err != nil {
		return fmt.Errorf("tool not found: %s", tool)
	}

	fmt.Printf("[SkillGod] Running %s with skills active\n", tool)
	c := exec.Command(toolBin, toolArgs...)
	c.Stdin  = os.Stdin
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Env   = env
	return c.Run()
}
