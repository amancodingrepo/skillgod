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
	cyan   := color.New(color.FgCyan).SprintFunc()
	dim    := color.New(color.Faint).SprintFunc()
	bold   := color.New(color.Bold).SprintFunc()

	escaped := strings.ReplaceAll(task, `\`, `\\`)
	escaped  = strings.ReplaceAll(escaped, "'", `\'`)
	// Output per skill: score|name|why-fired|description
	// why-fired = space-joined matched reasons, e.g. '"debug" "traceback" #python'
	code := fmt.Sprintf(
		`import time;from skills import find_skills,_load_all_skills;`+
		`t=time.perf_counter();r=find_skills('%s', top_k=5);`+
		`ms=(time.perf_counter()-t)*1000;`+
		`print(f"__META__{len(_load_all_skills())}|{ms:.0f}");`+
		`[print(f"{x['score']:.2f}|{x['name']}|{' '.join(x.get('matched',[]))[:30]}|{x.get('description','')[:70]}") for x in r]`,
		escaped,
	)

	out, err := runPython(sgRoot, code)
	if err != nil {
		return fmt.Errorf("skills engine error: %w", err)
	}

	total, ms := "1,944", "12"
	type result struct{ score, name, why, desc string }
	var results []result
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "__META__") {
			meta := strings.SplitN(strings.TrimPrefix(line, "__META__"), "|", 2)
			if len(meta) == 2 {
				total, ms = meta[0], meta[1]
			}
			continue
		}
		parts := strings.SplitN(line, "|", 4)
		if len(parts) == 4 {
			results = append(results, result{parts[0], parts[1], parts[2], parts[3]})
		}
	}

	if len(results) == 0 {
		fmt.Println(yellow("No skills matched: " + task))
		return nil
	}

	fmt.Printf("\nSkills for: %s\n\n", bold(`"`+task+`"`))
	for _, r := range results {
		// Line 1: name  score  why-fired
		fmt.Printf("  %-24s %s  %s\n",
			bold(r.name),
			green(r.score),
			cyan(r.why),
		)
		// Line 2: description (indented, dimmed)
		if r.desc != "" {
			fmt.Printf("    %s\n", dim(r.desc))
		}
		fmt.Println()
	}
	fmt.Printf("  %s\n",
		dim(fmt.Sprintf("Scored %s skills in %sms  ·  top %d auto-inject via MCP",
			total, ms, len(results))),
	)
	return nil
}
