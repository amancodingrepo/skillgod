package cmd

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var promoteCmd = &cobra.Command{
	Use:   "promote",
	Short: "Review and approve auto-learned skills for vault promotion",
	Long: `Layer 2: promotion queue.

Auto-learned skills land in vault/meta/ at confidence <= 0.69.
When a skill reaches confidence >= 0.70 with a good description,
it enters the promotion queue for your review.

  sg promote          Interactive review (approve / reject / skip)
  sg promote --list   Show queue without interactive prompts
  sg promote --scan   Scan meta/ and enqueue new candidates`,
	RunE: runPromote,
}

var (
	promoteList bool
	promoteScan bool
)

func init() {
	promoteCmd.Flags().BoolVar(&promoteList, "list", false, "List queue without prompting")
	promoteCmd.Flags().BoolVar(&promoteScan, "scan", false, "Scan meta/ for new candidates")
}

func runPromote(cmd *cobra.Command, args []string) error {
	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	bold   := color.New(color.Bold).SprintFunc()
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	red    := color.New(color.FgRed).SprintFunc()
	cyan   := color.New(color.FgCyan).SprintFunc()

	// Scan first if requested
	if promoteScan {
		out, err := runPython(sgRoot,
			"from variants import auto_enqueue_candidates; print(auto_enqueue_candidates())")
		if err != nil {
			return fmt.Errorf("scan error: %w", err)
		}
		fmt.Printf("Scanned meta/ → %s candidate(s) added to queue\n",
			green(strings.TrimSpace(out)))
	}

	// Fetch queue
	queueCode := `
from variants import get_promotion_queue, queue_stats
import json
q = get_promotion_queue('pending')
s = queue_stats()
print(json.dumps({"queue": q, "stats": s}))
`
	out, err := runPython(sgRoot, strings.ReplaceAll(queueCode, "\n", "; "))
	if err != nil {
		return fmt.Errorf("queue error: %w", err)
	}
	out = strings.TrimSpace(out)

	// Parse stats
	statsIdx := strings.Index(out, `"stats"`)
	pending  := "0"
	approved := "0"
	rejected := "0"
	if statsIdx != -1 {
		statsChunk := out[statsIdx:]
		pending  = extractJSONVal("pending", statsChunk)
		approved = extractJSONVal("approved", statsChunk)
		rejected = extractJSONVal("rejected", statsChunk)
	}

	fmt.Println(bold("\nSkillGod Promotion Queue"))
	fmt.Println("─────────────────────────────────")
	fmt.Printf("  Pending: %s   Approved: %s   Rejected: %s\n\n",
		yellow(pending), green(approved), red(rejected))

	if pending == "0" || pending == "" {
		fmt.Println(cyan("  Queue is empty."))
		fmt.Println("  Run 'sg promote --scan' to check vault/meta/ for candidates.")
		return nil
	}

	// Parse queue items
	items := parsePromoteQueue(out)
	if len(items) == 0 {
		fmt.Println("  No pending items.")
		return nil
	}

	if promoteList {
		// Non-interactive listing
		fmt.Printf("  Pending (%d):\n\n", len(items))
		for i, item := range items {
			fmt.Printf("  [%d] %-40s conf=%-5s\n", i+1,
				item["skill_name"], item["confidence"])
			if desc := item["description"]; desc != "" {
				fmt.Printf("       %s\n", yellow(truncate(desc, 70)))
			}
			fmt.Println()
		}
		fmt.Printf("  Run %s to review interactively.\n", bold("sg promote"))
		return nil
	}

	// Interactive review
	fmt.Printf("  Pending: %s skill(s) ready for review\n\n", bold(pending))
	scanner := bufio.NewScanner(os.Stdin)

	for i, item := range items {
		id   := item["id"]
		name := item["skill_name"]
		conf := item["confidence"]
		desc := item["description"]

		fmt.Printf("─── [%d/%d] %s ─────────────\n", i+1, len(items), bold(name))
		fmt.Printf("  Confidence : %s\n", green(conf))
		if desc != "" {
			fmt.Printf("  Description: %s\n", yellow(truncate(desc, 80)))
		}
		fmt.Println()
		fmt.Printf("  Approve [a] / Reject [r] / Skip [s] / Quit [q]: ")

		scanner.Scan()
		choice := strings.ToLower(strings.TrimSpace(scanner.Text()))

		switch choice {
		case "a", "approve", "y":
			approveCode := fmt.Sprintf(
				"from variants import approve_promotion; print(approve_promotion(%s))", id)
			res, _ := runPython(sgRoot, approveCode)
			if strings.Contains(res, "True") {
				fmt.Printf("  %s %s → promoted to vault/coding/\n",
					green("[APPROVED]"), name)
			} else {
				fmt.Printf("  %s (file may have moved)\n", yellow("[skipped]"))
			}

		case "r", "reject", "n":
			rejectCode := fmt.Sprintf(
				"from variants import reject_promotion; reject_promotion(%s)", id)
			runPython(sgRoot, rejectCode)
			fmt.Printf("  %s %s\n", red("[REJECTED]"), name)

		case "q", "quit":
			fmt.Println("\n  Exiting. Resume with: sg promote")
			return nil

		default:
			fmt.Printf("  %s %s\n", yellow("[skipped]"), name)
		}
		fmt.Println()
	}

	fmt.Println(bold("Review complete."))
	fmt.Println("Run 'sg stats' to see updated vault counts.")
	return nil
}

// ── helpers ────────────────────────────────────────────────────────────────

func extractJSONVal(key, s string) string {
	idx := strings.Index(s, `"`+key+`":`)
	if idx == -1 {
		return "0"
	}
	rest := strings.TrimSpace(s[idx+len(key)+3:])
	end  := strings.IndexAny(rest, ",}")
	if end == -1 {
		return strings.Trim(rest, `" `)
	}
	return strings.Trim(rest[:end], `" `)
}

func parsePromoteQueue(raw string) []map[string]string {
	var items []map[string]string
	// Each item starts with {"id":
	parts := strings.Split(raw, `{"id":`)
	for _, p := range parts[1:] {
		item := map[string]string{
			"id":          strings.TrimSpace(strings.SplitN(p, ",", 2)[0]),
			"skill_name":  extractJSONVal("skill_name", p),
			"confidence":  extractJSONVal("confidence", p),
			"description": extractJSONVal("description", p),
		}
		items = append(items, item)
	}
	return items
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-3] + "..."
}
