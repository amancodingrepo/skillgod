package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"

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

	// Auto-restore Pro. The reinstall above lays down only the free engine, so a
	// paying user would drop to free. If this machine has a saved license
	// (persisted by a prior `sg sync --key`, and NOT wiped by the engine
	// overwrite), re-sync the encrypted Pro vault automatically — no key
	// re-entry. runSync with no --key picks up the saved key.
	if sgRoot, rerr := findSkillGodRoot(); rerr == nil {
		cached, _ := runPython(sgRoot,
			"from license import get_cached_key; print(get_cached_key())")
		if strings.TrimSpace(cached) != "" {
			fmt.Println()
			fmt.Println(bold("Restoring your Pro vault..."))
			licenseKey = "" // ensure runSync uses the saved key
			if serr := runSync(cmd, args); serr != nil {
				fmt.Printf("  %s couldn't auto-restore Pro — run: sg sync\n",
					color.New(color.FgYellow).SprintFunc()("[warn]"))
			}
		}
	}

	fmt.Println()
	fmt.Printf("Run %s to confirm, then restart your IDE.\n", bold("sg --version"))
	return nil
}
