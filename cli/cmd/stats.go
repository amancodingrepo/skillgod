package cmd

import (
	"fmt"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var statsCmd = &cobra.Command{
	Use:   "stats",
	Short: "Show vault statistics and health",
	RunE:  runStats,
}

func runStats(cmd *cobra.Command, args []string) error {
	bold  := color.New(color.Bold).SprintFunc()
	green := color.New(color.FgGreen).SprintFunc()

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	code := `from skills import get_active_skill_count as A, get_full_vault_count as F, get_license_tier as T; from pathlib import Path; vault=Path('vault'); cats={d.name:len(list(d.rglob('*.md'))) for d in sorted(vault.iterdir()) if d.is_dir()}; print(f'TIER:{T()}'); print(f'ACTIVE:{A()}'); print(f'FULL:{F()}'); [print(f'{k}:{v}') for k,v in cats.items()]`

	out, err := runPython(sgRoot, code)
	if err != nil {
		fmt.Println(bold("SkillGod Vault"))
		fmt.Println("Could not read vault stats:", err)
		return nil
	}

	var tier, active, full string
	var cats []string
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		parts := strings.SplitN(strings.TrimSpace(line), ":", 2)
		if len(parts) != 2 {
			continue
		}
		switch parts[0] {
		case "TIER":
			tier = parts[1]
		case "ACTIVE":
			active = parts[1]
		case "FULL":
			full = parts[1]
		default:
			cats = append(cats, fmt.Sprintf("  %-20s %s", parts[0], parts[1]))
		}
	}

	fmt.Println(bold("\nSkillGod Vault Stats"))
	fmt.Println("────────────────────────")
	fmt.Printf("  %s %s skills\n", bold(fmt.Sprintf("Active (%s tier):", tier)), green(active))
	fmt.Printf("  %s %s skills\n\n", bold("Full vault:      "), full)
	for _, line := range cats {
		fmt.Println(line)
	}
	return nil
}
