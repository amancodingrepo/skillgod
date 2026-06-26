package cmd

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var referralCmd = &cobra.Command{
	Use:   "referral",
	Short: "Show your referral code and stats",
	RunE:  runReferral,
}

func init() {
	rootCmd.AddCommand(referralCmd)
}

func runReferral(cmd *cobra.Command, args []string) error {
	bold   := color.New(color.Bold).SprintFunc()
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	dim    := color.New(color.Faint).SprintFunc()

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	// Get install_id from local config
	installID, err := runPython(sgRoot, `
import sys, json
sys.path.insert(0, 'engine')
try:
    from license import get_install_id
    print(get_install_id())
except Exception as e:
    print("")
`)
	if err != nil || strings.TrimSpace(installID) == "" {
		return fmt.Errorf("could not read install ID — run sg sync --key first")
	}
	installID = strings.TrimSpace(installID)

	// Get API base URL
	apiBase := os.Getenv("SKILLGOD_API")
	if apiBase == "" {
		apiBase = "https://api.skillgod.dev"
	}

	// Fetch referral stats from API
	url := fmt.Sprintf("%s/v1/referral/stats?install_id=%s", apiBase, installID)
	resp, err := http.Get(url)
	if err != nil {
		return fmt.Errorf("could not reach SkillGod API: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var stats map[string]interface{}
	if err := json.Unmarshal(body, &stats); err != nil {
		return fmt.Errorf("invalid response from API")
	}

	if errMsg, ok := stats["error"].(string); ok {
		return fmt.Errorf("%s", errMsg)
	}

	code, _ := stats["referral_code"].(string)
	total,   _ := stats["total_referrals"].(float64)
	converted, _ := stats["converted"].(float64)
	earned,  _ := stats["free_months_earned"].(float64)
	pending, _ := stats["pending"].(float64)

	fmt.Println()
	fmt.Println(bold("SkillGod Referral"))
	fmt.Println("────────────────────────────────────")
	fmt.Println()

	if code == "" {
		fmt.Println(yellow("  No referral code yet."))
		fmt.Println(dim("  Activate Pro to get your personal code:"))
		fmt.Println(dim("    skillgod.dev/#pricing"))
		fmt.Println()
		return nil
	}

	fmt.Printf("  Your code:  %s\n", bold(green(code)))
	fmt.Println()
	fmt.Printf("  Share this link:\n")
	fmt.Printf("  %s\n", yellow(fmt.Sprintf("skillgod.dev/?ref=%s", code)))
	fmt.Println()
	fmt.Println("  Stats:")
	fmt.Printf("    Referred:  %s people\n", bold(fmt.Sprintf("%.0f", total)))
	fmt.Printf("    Converted: %s paying\n", bold(green(fmt.Sprintf("%.0f", converted))))
	fmt.Printf("    Earned:    %s months free\n", bold(green(fmt.Sprintf("%.0f", earned))))
	fmt.Printf("    Pending:   %s\n", fmt.Sprintf("%.0f", pending))
	fmt.Println()
	fmt.Println(dim("  Your friend gets 20% off their first month."))
	fmt.Println(dim("  You get 1 free month per conversion. No limit."))
	fmt.Println()

	return nil
}
