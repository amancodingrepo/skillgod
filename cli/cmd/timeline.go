package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var timelineLimit int

var timelineCmd = &cobra.Command{
	Use:   "timeline",
	Short: "Show the git-aware memory timeline for this project",
	Long: `Show recent decisions, patterns, and errors SkillGod captured for this
project — newest first. Memory is local to your machine.`,
	RunE: runTimeline,
}

func init() {
	timelineCmd.Flags().IntVar(&timelineLimit, "limit", 30, "max entries to show")
	rootCmd.AddCommand(timelineCmd)
}

func runTimeline(cmd *cobra.Command, args []string) error {
	bold   := color.New(color.Bold).SprintFunc()
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	cyan   := color.New(color.FgCyan).SprintFunc()
	dim    := color.New(color.Faint).SprintFunc()

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	// Project = current directory name (matches how sg init / runtime tag memory)
	project := "default"
	if cwd, err := os.Getwd(); err == nil {
		project = filepath.Base(cwd)
	}

	code := fmt.Sprintf(
		`import json;from memory import get_timeline;`+
			`print(json.dumps(get_timeline('%s', %d)))`,
		strings.ReplaceAll(project, "'", `\'`), timelineLimit,
	)
	out, err := runPython(sgRoot, code)
	if err != nil {
		return fmt.Errorf("memory engine error: %w", err)
	}

	var entries []struct {
		Kind      string `json:"kind"`
		Summary   string `json:"summary"`
		CreatedAt string `json:"created_at"`
	}
	if json.Unmarshal([]byte(strings.TrimSpace(out)), &entries) != nil || len(entries) == 0 {
		fmt.Printf("\n%s\n", bold("SkillGod timeline — "+project))
		fmt.Println(dim("  No memory captured yet. It builds automatically as you code."))
		fmt.Println()
		return nil
	}

	// Colour per memory kind
	kindColor := func(k string) string {
		switch k {
		case "decision":
			return green("[decision]")
		case "error":
			return color.New(color.FgRed).Sprint("[error]")
		case "pattern":
			return cyan("[pattern]")
		default:
			return yellow("[" + k + "]")
		}
	}

	fmt.Printf("\n%s\n\n", bold("SkillGod timeline — "+project))
	for _, e := range entries {
		fmt.Printf("  %s %s %s %s\n",
			kindColor(e.Kind),
			e.Summary,
			dim("·"),
			dim(fmtTimelineDate(e.CreatedAt)),
		)
	}
	fmt.Println()
	return nil
}

// fmtTimelineDate turns an ISO timestamp into "Mar 15"; falls back to the date prefix.
func fmtTimelineDate(iso string) string {
	for _, layout := range []string{
		"2006-01-02T15:04:05.000000",
		"2006-01-02T15:04:05",
		"2006-01-02T15:04:05Z07:00",
	} {
		if t, err := time.Parse(layout, iso); err == nil {
			return t.Format("Jan 2")
		}
	}
	if len(iso) >= 10 {
		return iso[:10]
	}
	return iso
}
