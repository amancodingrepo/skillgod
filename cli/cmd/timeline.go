package cmd

import (
	"encoding/json"
	"fmt"
	"os"
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

	// BUG FIX — this used to key on filepath.Base(cwd) (just the folder
	// name), while hooks and the MCP server both key memory on
	// derive_project_id() (git-remote-normalized, or folder+abspath-hash).
	// For any project with a git remote, those two never matched, so
	// `sg timeline` was querying under a project key nothing was ever
	// written to — it would show "No memory captured yet" even with real
	// captured rows sitting in the DB under the correct id. Same bug class
	// as the original hooks/MCP project-id mismatch, just found in a third
	// place. Resolve the same way everywhere else does — one Python call
	// returning both the resolved project id and the timeline, rather than
	// two separate subprocess round-trips for one derived value.
	//
	// SECOND BUG FOUND WHILE FIXING THE FIRST — runPython() always sets
	// c.Dir = sgRoot for the child process (needed so its own relative
	// imports work), which means derive_project_id() called with NO
	// argument inside that subprocess resolves against sgRoot, not the
	// directory `sg timeline` was actually run from. Must capture the real
	// caller's cwd here in Go, before runPython changes it, and pass it in
	// explicitly — derive_project_id(cwd) accepts exactly this for exactly
	// this reason.
	cwd, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("cannot resolve current directory: %w", err)
	}
	code := fmt.Sprintf(
		`import json;from memory import get_timeline, derive_project_id;`+
			`p=derive_project_id(%q);`+
			`print(json.dumps({"project": p, "entries": get_timeline(p, %d)}))`,
		cwd, timelineLimit,
	)
	out, err := runPython(sgRoot, code)
	if err != nil {
		return fmt.Errorf("memory engine error: %w", err)
	}

	var result struct {
		Project string `json:"project"`
		Entries []struct {
			Kind      string `json:"kind"`
			Summary   string `json:"summary"`
			Detail    string `json:"detail"`
			CreatedAt string `json:"created_at"`
		} `json:"entries"`
	}
	if json.Unmarshal([]byte(strings.TrimSpace(out)), &result) != nil {
		return fmt.Errorf("memory engine error: could not parse timeline output")
	}
	project := result.Project
	if project == "" {
		project = "default"
	}
	if len(result.Entries) == 0 {
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

	// gitTag extracts a "[branch:X commit:Y]" tag save_with_git() appends to
	// `detail`, if present — this is the git-branch attribution sg timeline
	// is supposed to surface (see engine/memory.py's get_git_context()).
	gitTag := func(detail string) string {
		start := strings.Index(detail, "[branch:")
		if start == -1 {
			return ""
		}
		end := strings.Index(detail[start:], "]")
		if end == -1 {
			return ""
		}
		return detail[start : start+end+1]
	}

	fmt.Printf("\n%s\n\n", bold("SkillGod timeline — "+project))
	for _, e := range result.Entries {
		tag := gitTag(e.Detail)
		if tag != "" {
			fmt.Printf("  %s %s %s %s %s\n",
				kindColor(e.Kind),
				e.Summary,
				dim(tag),
				dim("·"),
				dim(fmtTimelineDate(e.CreatedAt)),
			)
		} else {
			fmt.Printf("  %s %s %s %s\n",
				kindColor(e.Kind),
				e.Summary,
				dim("·"),
				dim(fmtTimelineDate(e.CreatedAt)),
			)
		}
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
