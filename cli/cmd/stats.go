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

	code := `from pathlib import Path; vault=Path('vault'); cats={d.name:len(list(d.glob('*.md'))) for d in sorted(vault.iterdir()) if d.is_dir()}; total=sum(cats.values()); print(f'TOTAL:{total}'); [print(f'{k}:{v}') for k,v in cats.items()]`

	out, err := runPython(sgRoot, code)
	if err != nil {
		fmt.Println(bold("SkillGod Vault"))
		fmt.Println("Could not read vault stats:", err)
		return nil
	}

	fmt.Println(bold("\nSkillGod Vault Stats"))
	fmt.Println("────────────────────────")
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		parts := strings.SplitN(line, ":", 2)
		if len(parts) == 2 {
			if parts[0] == "TOTAL" {
				fmt.Printf("  %s %s skills\n\n", bold("Total:"), green(parts[1]))
			} else {
				fmt.Printf("  %-20s %s\n", parts[0], parts[1])
			}
		}
	}
	return nil
}
