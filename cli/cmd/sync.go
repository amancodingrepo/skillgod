package cmd

import (
	"fmt"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var licenseKey string

var syncCmd = &cobra.Command{
	Use:   "sync",
	Short: "Sync vault with latest skills",
	Long: `Sync your skill vault.

Free tier:  sg sync                          (indexes local vault, 30 starter skills)
Pro tier:   sg sync --key YOUR_LICENSE_KEY   (decrypts full vault, 1071 skills active)`,
	RunE: runSync,
}

func init() {
	syncCmd.Flags().StringVar(&licenseKey, "key", "", "License key for pro vault")
}

func runSync(cmd *cobra.Command, args []string) error {
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	red    := color.New(color.FgRed).SprintFunc()
	bold   := color.New(color.Bold).SprintFunc()

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	if licenseKey == "" {
		// Free tier — index local vault
		fmt.Println(bold("Syncing free tier (30 starter skills)..."))
		fmt.Println(yellow("Upgrade to Pro for 1071+ skills: skillgod.dev"))
		out, _ := runPython(sgRoot, "from skills import rebuild_index; print(rebuild_index())")
		fmt.Printf("Index updated: %s skills\n", green(strings.TrimSpace(out)))
		return nil
	}

	// ── Pro tier: full encrypted vault sync ──────────────────────────────
	fmt.Println(bold("Validating license key..."))

	// Step 1: verify key can decrypt sentinel
	escaped := strings.ReplaceAll(licenseKey, "'", `\'`)
	verifyCode := fmt.Sprintf(
		`from encryption import verify_key; print(verify_key('%s'))`,
		escaped,
	)
	verifyOut, verifyErr := runPython(sgRoot, verifyCode)
	verifyOut = strings.TrimSpace(verifyOut)

	// If vault_encrypted/ doesn't exist yet, validate via LemonSqueezy instead
	if verifyErr != nil || verifyOut == "" {
		// Fall back to LemonSqueezy license check
		lsCode := fmt.Sprintf(
			`from license import check_license; check_license('%s')`,
			escaped,
		)
		lsOut, lsErr := runPython(sgRoot, lsCode)
		if lsErr != nil {
			fmt.Printf("%s License validation error: %v\n", red("[ERROR]"), lsErr)
			fmt.Println("Check your internet connection or run: sg sync --key KEY")
			return nil
		}
		lsOut = strings.TrimSpace(lsOut)
		if !strings.HasPrefix(lsOut, "LICENSE_VALID:") {
			reason := strings.TrimPrefix(lsOut, "LICENSE_INVALID:")
			fmt.Printf("%s Invalid license key\n", red("[BLOCKED]"))
			if reason != "" {
				fmt.Printf("  Reason: %s\n", reason)
			}
			fmt.Println()
			fmt.Println("  Purchase a license at: skillgod.dev")
			return nil
		}
		fmt.Printf("%s License valid (online verified)\n", green("[OK]"))
	} else if verifyOut == "False" {
		fmt.Printf("%s Invalid license key — cannot decrypt vault\n", red("[BLOCKED]"))
		fmt.Println("  Purchase a license at: skillgod.dev")
		fmt.Println("  Free tier: sg sync  (no key needed)")
		return nil
	} else {
		fmt.Printf("%s License key valid\n", green("[OK]"))
	}

	// Step 2: decrypt full vault in memory and write to vault/
	fmt.Println()
	fmt.Println(bold("Decrypting vault..."))
	syncCode := fmt.Sprintf(
		`from encryption import sync_encrypted_vault; `+
		`from skills import rebuild_index; `+
		`n = sync_encrypted_vault('%s'); `+
		`idx = rebuild_index(); `+
		`print(f"SYNCED:{n}:{idx}")`,
		escaped,
	)
	syncOut, syncErr := runPython(sgRoot, syncCode)
	if syncErr != nil {
		fmt.Printf("%s Vault decrypt failed: %v\n", red("[ERROR]"), syncErr)
		fmt.Println("  Is vault_encrypted/ present? Run: python engine/encryption.py encrypt --key KEY")
		return nil
	}

	syncOut = strings.TrimSpace(syncOut)
	if strings.HasPrefix(syncOut, "SYNCED:") {
		parts := strings.Split(strings.TrimPrefix(syncOut, "SYNCED:"), ":")
		written := parts[0]
		indexed := ""
		if len(parts) > 1 {
			indexed = parts[1]
		}
		fmt.Printf("  Vault synced: %s skills active\n", green(indexed))
		fmt.Printf("  Files written: %s\n", green(written))
		fmt.Println()
		fmt.Printf("%s Full vault active. Skills injecting at every prompt.\n", green("[OK]"))
	} else {
		fmt.Printf("%s Unexpected sync output: %s\n", yellow("[warn]"), syncOut)
	}

	return nil
}
