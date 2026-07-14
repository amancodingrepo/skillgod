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
var timelineAll bool
var timelineMin float64

var timelineCmd = &cobra.Command{
	Use:   "timeline",
	Short: "Show the git-aware memory timeline for this project",
	Long: `Show recent decisions, patterns, and errors SkillGod captured for this
project — newest first. Memory is local to your machine.

Every commit is captured; by default only importance >= 0.6 (real decisions)
is shown. Use --all to include low-importance/noise commits, or --min <float>
to set your own threshold.`,
	RunE: runTimeline,
}

func init() {
	timelineCmd.Flags().IntVar(&timelineLimit, "limit", 30, "max entries to show")
	timelineCmd.Flags().BoolVar(&timelineAll, "all", false, "show every captured commit, including low-importance noise")
	timelineCmd.Flags().Float64Var(&timelineMin, "min", 0.6, "minimum importance to show (0.0–1.0)")
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
	minImp := timelineMin
	if timelineAll {
		minImp = 0.0
	}
	code := fmt.Sprintf(
		`import json,os;from memory import get_timeline, timeline_counts, derive_project_id;`+
			`p=derive_project_id(%q);`+
			`git=os.path.isdir(os.path.join(%q, ".git")) or bool(__import__("subprocess").run(["git","-C",%q,"rev-parse","--git-dir"],capture_output=True).returncode==0);`+
			`print(json.dumps({"project": p, "is_git_repo": git, "counts": timeline_counts(p, %f), "entries": get_timeline(p, %d, %f)}))`,
		cwd, cwd, cwd, minImp, timelineLimit, minImp,
	)
	out, err := runPython(sgRoot, code)
	if err != nil {
		return fmt.Errorf("memory engine error: %w", err)
	}

	var result struct {
		Project   string `json:"project"`
		IsGitRepo bool   `json:"is_git_repo"`
		Counts    struct {
			Total  int `json:"total"`
			Hidden int `json:"hidden"`
			Shown  int `json:"shown"`
		} `json:"counts"`
		Entries []struct {
			Kind       string  `json:"kind"`
			Summary    string  `json:"summary"`
			Detail     string  `json:"detail"`
			CreatedAt  string  `json:"created_at"`
			Importance float64 `json:"importance"`
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
		printTimelineEmptyState(sgRoot, cwd, project, result.IsGitRepo,
			result.Counts.Total, result.Counts.Hidden, green, yellow, cyan, dim)
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
	if !timelineAll && result.Counts.Hidden > 0 {
		fmt.Printf("\n  %s\n", dim(fmt.Sprintf(
			"%d low-importance entr%s hidden — sg timeline --all",
			result.Counts.Hidden, plural(result.Counts.Hidden, "y", "ies"))))
	}
	fmt.Println()
	return nil
}

func plural(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// printTimelineEmptyState explains, per context, WHY the timeline is empty
// instead of a single generic line (Task 7.1): a dead/absent watcher, a
// non-git dir, or rows hidden below the importance threshold.
func printTimelineEmptyState(sgRoot, cwd, project string, isGitRepo bool,
	total, hidden int, green, yellow, cyan, dim func(...interface{}) string) {
	switch {
	case hidden > 0:
		// Rows exist but all below the threshold.
		fmt.Printf("  %s\n", dim(fmt.Sprintf(
			"%d low-importance entr%s hidden below the 0.6 default.", hidden, plural(hidden, "y", "ies"))))
		fmt.Printf("  %s\n", cyan("sg timeline --all")+dim("  shows every captured commit."))
	case !isGitRepo:
		fmt.Printf("  %s\n", dim("This directory isn't inside a git repository, so the git"))
		fmt.Printf("  %s\n", dim("watcher captures nothing here. Memory builds from commits"))
		fmt.Printf("  %s\n", dim("(and, in Claude Code, from decisions stated in a session)."))
	case !isWatcherAliveForProject(sgRoot, cwd):
		fmt.Printf("  %s\n", dim("No memory yet — and no watcher is running for this project."))
		fmt.Printf("  %s\n", cyan("sg watch")+dim("  starts it; then a commit with decision language"))
		fmt.Printf("  %s\n", dim("(e.g. \"decision: use X instead of Y\") lands here automatically."))
	default:
		fmt.Printf("  %s\n", dim("No memory captured yet. State a decision in a Claude session,"))
		fmt.Printf("  %s\n", dim("or make a commit like \"decision: use Postgres instead of Redis\"."))
		fmt.Printf("  %s\n", dim("In Cursor/Windsurf/Antigravity, capture is via commits or the"))
		fmt.Printf("  %s\n", dim("model calling sg_save_memory."))
	}
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
