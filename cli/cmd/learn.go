package cmd

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var learnCmd = &cobra.Command{
	Use:   "learn",
	Short: "Save a Claude output as a new skill",
	Long: `Interactively save a session output as a skill.

You will be prompted for:
  - The task description
  - The output to learn from (paste, end with ---END---)`,
	RunE: runLearn,
}

func runLearn(cmd *cobra.Command, args []string) error {
	green := color.New(color.FgGreen).SprintFunc()
	bold  := color.New(color.Bold).SprintFunc()

	scanner := bufio.NewScanner(os.Stdin)

	fmt.Print(bold("Task: "))
	scanner.Scan()
	task := scanner.Text()

	fmt.Println(bold("Output (end with ---END--- on its own line):"))
	var lines []string
	for scanner.Scan() {
		line := scanner.Text()
		if line == "---END---" {
			break
		}
		lines = append(lines, line)
	}
	output := strings.Join(lines, "\n")

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	maxLen := len(output)
	if maxLen > 2000 {
		maxLen = 2000
	}
	escapedTask   := strings.ReplaceAll(task, "'", `\'`)
	escapedOutput := strings.ReplaceAll(output[:maxLen], "'", `\'`)
	escapedOutput  = strings.ReplaceAll(escapedOutput, "\n", `\n`)

	code := fmt.Sprintf(
		`from skills import learn_skill; path = learn_skill('%s', '%s'); print(path if path else 'not_reusable')`,
		escapedTask, escapedOutput,
	)

	out, err := runPython(sgRoot, code)
	if err != nil {
		return fmt.Errorf("learn error: %w", err)
	}

	out = strings.TrimSpace(out)
	if out == "not_reusable" {
		fmt.Println("Output did not meet reusability threshold.")
		fmt.Println("Needs: structured steps + examples + 60+ words.")
	} else {
		fmt.Printf("Skill learned -> %s\n", green(out))
	}
	return nil
}
