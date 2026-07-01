package cmd

import (
	"fmt"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

// vaultCmd shows local vault status: skill counts by category, the active
// license tier (free vs pro), and whether an encrypted vault is present.
var vaultCmd = &cobra.Command{
	Use:   "vault",
	Short: "Show local vault status — skill counts by category and license tier",
	Long: `Show the status of your local skill vault.

Reports the total number of skills, a per-category breakdown, the active
license tier (free vs pro), and whether an encrypted vault is present on this
machine. Reads the vault on disk via the SkillGod python engine.`,
	RunE: runVault,
}

func init() {
	rootCmd.AddCommand(vaultCmd)
}

// runVault gathers vault status from the python engine and prints a summary of
// skill counts per category, the active tier, and encrypted-vault presence.
func runVault(cmd *cobra.Command, args []string) error {
	bold   := color.New(color.Bold).SprintFunc()
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	dim    := color.New(color.Faint).SprintFunc()

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	// Category counts (mirror stats.go).
	statsCode := `from pathlib import Path; vault=Path('vault'); ` +
		`cats={d.name:len(list(d.glob('*.md'))) for d in sorted(vault.iterdir()) if d.is_dir()} if vault.is_dir() else {}; ` +
		`total=sum(cats.values()); print(f'TOTAL:{total}'); ` +
		`[print(f'{k}:{v}') for k,v in cats.items()]`

	out, err := runPython(sgRoot, statsCode)
	if err != nil {
		return fmt.Errorf("could not read vault: %w", err)
	}

	fmt.Println(bold("\nSkillGod Vault Status"))
	fmt.Println("────────────────────────")

	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		parts := strings.SplitN(strings.TrimSpace(line), ":", 2)
		if len(parts) != 2 {
			continue
		}
		if parts[0] == "TOTAL" {
			fmt.Printf("  %s %s skills\n\n", bold("Total:"), green(parts[1]))
		} else {
			fmt.Printf("  %-20s %s\n", parts[0], parts[1])
		}
	}

	// Encrypted-vault presence (drives tier detection). vault_encrypted/ holds
	// the pro blobs; its presence means a pro vault has been fetched/decrypted.
	encCode := `from pathlib import Path; ` +
		`print('ENC:1' if Path('vault_encrypted').is_dir() and any(Path('vault_encrypted').rglob('*.sg')) else 'ENC:0')`

	encOut, encErr := runPython(sgRoot, encCode)
	encrypted := false
	if encErr == nil && strings.TrimSpace(encOut) == "ENC:1" {
		encrypted = true
	}

	fmt.Println()
	if encrypted {
		fmt.Printf("  %-20s %s\n", "Tier:", green("pro"))
		fmt.Printf("  %-20s %s\n", "Encrypted vault:", green("present"))
	} else {
		fmt.Printf("  %-20s %s\n", "Tier:", yellow("free"))
		fmt.Printf("  %-20s %s\n", "Encrypted vault:", dim("none"))
		fmt.Println()
		fmt.Println(dim("  Upgrade to Pro for 1,927+ skills: sg sync --key <YOUR_KEY>"))
	}

	return nil
}
