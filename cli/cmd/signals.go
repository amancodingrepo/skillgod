package cmd

import (
	"fmt"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var signalsCmd = &cobra.Command{
	Use:   "signals",
	Short: "Show local signal stats and top performing skills",
	Long: `Layer 2: local signal tracking.

Signals record whether skill injections led to good outcomes (accept)
or required rework. All data stays on your machine.

  sg signals          Show stats + top performing skills
  sg signals enable   Opt in to signal tracking (default off)
  sg signals disable  Turn off signal tracking`,
	RunE: runSignals,
}

var enableSignalsCmd = &cobra.Command{
	Use:   "enable",
	Short: "Enable signal tracking",
	RunE: func(cmd *cobra.Command, args []string) error {
		sgRoot, err := findSkillGodRoot()
		if err != nil {
			return err
		}
		green := color.New(color.FgGreen).SprintFunc()
		_, err = runPython(sgRoot, "from signals import enable; enable(); print('ok')")
		if err != nil {
			return fmt.Errorf("could not enable signals: %w", err)
		}
		fmt.Printf("%s Signal tracking enabled.\n", green("[OK]"))
		fmt.Println("Signals record accept/rework outcomes per skill.")
		fmt.Println("All data stays local. Run 'sg signals' to see stats.")
		return nil
	},
}

var disableSignalsCmd = &cobra.Command{
	Use:   "disable",
	Short: "Disable signal tracking",
	RunE: func(cmd *cobra.Command, args []string) error {
		sgRoot, err := findSkillGodRoot()
		if err != nil {
			return err
		}
		yellow := color.New(color.FgYellow).SprintFunc()
		_, err = runPython(sgRoot, "from signals import disable; disable(); print('ok')")
		if err != nil {
			return fmt.Errorf("could not disable signals: %w", err)
		}
		fmt.Printf("%s Signal tracking disabled.\n", yellow("[OFF]"))
		return nil
	},
}

func init() {
	signalsCmd.AddCommand(enableSignalsCmd)
	signalsCmd.AddCommand(disableSignalsCmd)
}

func runSignals(cmd *cobra.Command, args []string) error {
	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	bold   := color.New(color.Bold).SprintFunc()
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	red    := color.New(color.FgRed).SprintFunc()

	// Get stats
	statsCode := `
from signals import signal_stats, top_performing_skills, is_enabled
import json
print(json.dumps({
    "stats": signal_stats(),
    "top":   top_performing_skills(limit=10),
    "enabled": is_enabled(),
}))
`
	out, err := runPython(sgRoot, strings.ReplaceAll(statsCode, "\n", " "))
	if err != nil {
		return fmt.Errorf("signals engine error: %w", err)
	}

	// Simple line-based parsing (avoid JSON import in Go for now)
	out = strings.TrimSpace(out)
	if strings.Contains(out, `"enabled": false`) || strings.Contains(out, `"enabled":false`) {
		fmt.Println(bold("\nSkillGod Signals"))
		fmt.Println("────────────────────────")
		fmt.Printf("  Status: %s (opt-in required)\n", yellow("DISABLED"))
		fmt.Println()
		fmt.Printf("  Enable with: %s\n", bold("sg signals enable"))
		fmt.Println("  Signals track which skills lead to accepted vs reworked outputs.")
		fmt.Println("  All data stays local — never sent anywhere.")
		return nil
	}

	// Enabled — show stats
	fmt.Println(bold("\nSkillGod Signals"))
	fmt.Println("────────────────────────")

	// Extract key values
	getVal := func(key, s string) string {
		idx := strings.Index(s, `"`+key+`":`)
		if idx == -1 {
			return "?"
		}
		rest := s[idx+len(key)+3:]
		end  := strings.IndexAny(rest, ",}")
		if end == -1 {
			return strings.TrimSpace(rest)
		}
		return strings.TrimSpace(rest[:end])
	}

	total    := getVal("total", out)
	accepts  := getVal("accepts", out)
	reworks  := getVal("reworks", out)
	rate     := getVal("accept_rate", out)
	distinct := getVal("distinct_skills", out)

	fmt.Printf("  Total signals   : %s\n", green(total))
	fmt.Printf("  Accept rate     : %s%%\n", green(rate))
	fmt.Printf("  Accepts/Reworks : %s / %s\n", green(accepts), red(reworks))
	fmt.Printf("  Skills tracked  : %s\n", green(distinct))

	// Top skills section
	if strings.Contains(out, `"skill_name"`) {
		fmt.Println()
		fmt.Println(bold("  Top performing skills:"))
		lines := strings.Split(out, `"skill_name"`)
		for i, chunk := range lines[1:] {
			if i >= 10 {
				break
			}
			nameEnd := strings.Index(chunk, `"`)
			if nameEnd < 2 {
				continue
			}
			name := strings.Trim(chunk[:nameEnd], `: "`)
			fires := getVal("fires", chunk)
			avg   := getVal("avg_score", chunk)
			arate := getVal("accept_rate", chunk)
			fmt.Printf("    %-35s fires=%-4s accept=%s%%  avg=%s\n",
				name, fires, arate, avg)
		}
	} else {
		fmt.Println()
		fmt.Println(yellow("  No skill data yet (min 3 fires per skill to appear)."))
	}

	fmt.Println()
	fmt.Printf("  All data is local. API sync activates when %s is set.\n",
		bold("SKILLGOD_API"))
	return nil
}
