package cmd

import (
	"fmt"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var redeemCmd = &cobra.Command{
	Use:   "redeem [coupon-code]",
	Short: "Redeem a coupon code for free Pro access",
	Args:  cobra.ExactArgs(1),
	RunE:  runRedeem,
}

func init() {
	rootCmd.AddCommand(redeemCmd)
}

func runRedeem(cmd *cobra.Command, args []string) error {
	code   := strings.ToUpper(strings.TrimSpace(args[0]))
	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	green  := color.New(color.FgGreen).SprintFunc()
	red    := color.New(color.FgRed).SprintFunc()
	bold   := color.New(color.Bold).SprintFunc()

	fmt.Printf("\nRedeeming coupon: %s\n\n", bold(code))

	result, err := runPython(sgRoot, fmt.Sprintf(`
import sys, json
sys.path.insert(0, 'engine')
from coupons import redeem
from license import get_machine_id
machine_id = get_machine_id()
result = redeem('%s', machine_id)
print(json.dumps(result))
`, code))

	if err != nil {
		return fmt.Errorf("redemption error: %w", err)
	}

	result = strings.TrimSpace(result)

	if strings.Contains(result, `"success": true`) {
		fmt.Printf("  %s\n", green("Coupon redeemed successfully"))

		// Extract message
		if idx := strings.Index(result, `"message": "`); idx >= 0 {
			start := idx + 12
			end   := strings.Index(result[start:], `"`)
			if end > 0 {
				fmt.Printf("  %s\n", result[start:start+end])
			}
		}

		fmt.Println()
		fmt.Println("  Syncing Pro vault...")
		runPython(sgRoot, `
import sys
sys.path.insert(0, 'engine')
from skills import rebuild_index
rebuild_index()
`)
		fmt.Printf("  %s Pro vault active\n\n", green("OK"))

	} else {
		msg := "Redemption failed"
		if idx := strings.Index(result, `"message": "`); idx >= 0 {
			start := idx + 12
			end   := strings.Index(result[start:], `"`)
			if end > 0 {
				msg = result[start : start+end]
			}
		}
		fmt.Printf("  %s %s\n\n", red("FAILED"), msg)
	}
	return nil
}
