package cmd

import (
	"fmt"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var findCmd = &cobra.Command{
	Use:   "find [task]",
	Short: "Find skills matching a task",
	Args:  cobra.MinimumNArgs(1),
	RunE:  runFind,
}

func runFind(cmd *cobra.Command, args []string) error {
	task := strings.Join(args, " ")
	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	bold   := color.New(color.Bold).SprintFunc()

	escaped := strings.ReplaceAll(task, `\`, `\\`)
	escaped  = strings.ReplaceAll(escaped, "'", `\'`)
	code := fmt.Sprintf(
		`from skills import find_skills; results = find_skills('%s', top_k=5);`+
		`[print(f"{r['score']:.2f}|{r['name']}|{r.get('description','')[:60]}") for r in results]`,
		escaped,
	)

	out, err := runPython(sgRoot, code)
	if err != nil {
		return fmt.Errorf("skills engine error: %w", err)
	}

	out = strings.TrimSpace(out)
	if out == "" {
		fmt.Println(yellow("No skills matched: " + task))
		return nil
	}

	fmt.Printf("\nSkills for: %s\n\n", bold(task))
	for _, line := range strings.Split(out, "\n") {
		parts := strings.SplitN(line, "|", 3)
		if len(parts) == 3 {
			fmt.Printf("  %s  %s\n       %s\n\n",
				green(parts[0]),
				bold(parts[1]),
				parts[2],
			)
		}
	}
	return nil
}
