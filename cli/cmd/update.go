package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var updateCmd = &cobra.Command{
	Use:   "update",
	Short: "Update SkillGod to the latest version",
	Long: `Re-downloads and reinstalls the latest sg binary and engine bundle.

SkillGod has no background update checker, so this is the only way to pick
up a new release, including security fixes. Re-runs the same installer
served at skillgod.dev/install (or install.ps1 on Windows) — the checksum
verification and engine install steps are identical to a fresh install.`,
	RunE: runUpdate,
}

func runUpdate(cmd *cobra.Command, args []string) error {
	bold := color.New(color.Bold).SprintFunc()
	dim := color.New(color.Faint).SprintFunc()

	fmt.Printf("%s %s\n", bold("Current version:"), Version)
	fmt.Println(dim("Fetching the latest installer from skillgod.dev..."))
	fmt.Println()

	var c *exec.Cmd
	if runtime.GOOS == "windows" {
		c = exec.Command("powershell", "-NoProfile", "-Command",
			"iwr -useb https://skillgod.dev/install.ps1 | iex")
	} else {
		c = exec.Command("bash", "-c",
			"curl -fsSL https://skillgod.dev/install | sh")
	}
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	c.Stdin = os.Stdin
	if err := c.Run(); err != nil {
		return fmt.Errorf("update failed: %w", err)
	}

	fmt.Println()
	fmt.Printf("Run %s to confirm, then restart your IDE.\n", bold("sg --version"))
	return nil
}
