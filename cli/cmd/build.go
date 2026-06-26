package cmd

import (
	"bufio"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var buildCmd = &cobra.Command{
	Use:   "build",
	Short: "Interactively build a new skill",
	RunE:  runBuild,
}

func runBuild(cmd *cobra.Command, args []string) error {
	bold   := color.New(color.Bold).SprintFunc()
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	cyan   := color.New(color.FgCyan).SprintFunc()

	scanner := bufio.NewScanner(os.Stdin)

	fmt.Println(bold("\nSkillGod Skill Builder"))
	fmt.Println("─────────────────────────────────")
	fmt.Println(yellow("Tip: description must start with 'Use when...'"))
	fmt.Println()

	prompt := func(label string) string {
		fmt.Printf("%s: ", cyan(label))
		scanner.Scan()
		return strings.TrimSpace(scanner.Text())
	}

	name        := prompt("Skill name")
	description := prompt("Description (Use when...)")
	triggers    := prompt("Trigger words (comma separated)")
	tags        := prompt("Tags (comma separated)")
	category    := prompt("Category (coding/design/writing/devops/security/agents)")
	confidence  := prompt("Confidence 0.7-0.95 (press enter for 0.80)")

	if confidence == "" {
		confidence = "0.80"
	}
	if category == "" {
		category = "coding"
	}

	fmt.Println()
	fmt.Printf("%s (end with ---END---):\n", bold("Skill body"))
	var bodyLines []string
	for scanner.Scan() {
		line := scanner.Text()
		if line == "---END---" {
			break
		}
		bodyLines = append(bodyLines, line)
	}
	body := strings.Join(bodyLines, "\n")

	if !strings.HasPrefix(strings.ToLower(description), "use when") &&
		!strings.HasPrefix(strings.ToLower(description), "use this") {
		fmt.Println(yellow("\nWarning: description should start with 'Use when...'"))
		fmt.Println(yellow("Auto-prefixing for you."))
		if len(description) > 0 {
			description = "Use when " + strings.ToLower(description[:1]) + description[1:]
		}
	}

	slug := strings.ToLower(strings.ReplaceAll(name, " ", "-"))
	slug  = strings.ReplaceAll(slug, "/", "-")
	date  := time.Now().Format("2006-01-02")

	content := fmt.Sprintf(`---
name: %s
type: skill
tags: [%s]
triggers: [%s]
description: %s
confidence: %s
source: user-created
created: %s
uses: 0
---
%s`, name, tags, triggers, description, confidence, date, body)

	filename := fmt.Sprintf("vault/%s/%s-%s.md", category, date, slug)
	os.MkdirAll(fmt.Sprintf("vault/%s", category), 0755)

	if err := os.WriteFile(filename, []byte(content), 0644); err != nil {
		return fmt.Errorf("failed to write skill: %w", err)
	}

	fmt.Printf("\n%s Skill saved -> %s\n", green("[OK]"), filename)
	fmt.Println("Run 'sg stats' to verify, or 'sg find' to test discovery.")

	sgRoot, _ := findSkillGodRoot()
	runPython(sgRoot, "from skills import rebuild_index; rebuild_index()")
	return nil
}
