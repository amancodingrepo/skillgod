package cmd

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var doctorFull bool

var doctorCmd = &cobra.Command{
	Use:   "doctor",
	Short: "Diagnose the SkillGod install (version, hooks, DB, watcher, capture)",
	Long: `Run health checks over your install and print PASS/WARN/FAIL for each,
with a remediation hint. Exit code is non-zero if any check FAILs.

  sg doctor          fast checks
  sg doctor --full   also runs a live end-to-end memory-capture self-test`,
	RunE: runDoctor,
}

func init() {
	doctorCmd.Flags().BoolVar(&doctorFull, "full", false, "also run the live end-to-end capture self-test")
	rootCmd.AddCommand(doctorCmd)
}

func doctorLine(status, label, detail string) bool {
	var tag string
	switch status {
	case "PASS":
		tag = color.New(color.FgGreen).Sprint("PASS")
	case "WARN":
		tag = color.New(color.FgYellow).Sprint("WARN")
	default:
		tag = color.New(color.FgRed).Sprint("FAIL")
	}
	dim := color.New(color.Faint).SprintFunc()
	if detail != "" {
		fmt.Printf("  [%s] %-22s %s\n", tag, label, dim(detail))
	} else {
		fmt.Printf("  [%s] %-22s\n", tag, label)
	}
	return status != "FAIL"
}

func runDoctor(cmd *cobra.Command, args []string) error {
	bold := color.New(color.Bold).SprintFunc()
	fmt.Println(bold("\nSkillGod doctor"))

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		doctorLine("FAIL", "engine located", "~/.skillgod not found — reinstall from skillgod.dev/install")
		os.Exit(1)
	}
	cwd, _ := os.Getwd()
	allOK := true

	// --- Go-side check 1: binary vs engine version (Task 4) ---
	if mismatched, ev := engineDrift(); mismatched {
		allOK = doctorLine("FAIL", "version match", fmt.Sprintf("engine %s != sg %s — run sg update", ev, Version)) && allOK
	} else {
		doctorLine("PASS", "version match", fmt.Sprintf("sg %s, engine %s", Version, ev))
	}

	// --- Go-side check 6: watcher status for this project (Task 6.6) ---
	switch {
	case !isInsideGitRepo(cwd):
		doctorLine("WARN", "watcher (this project)", "current dir is not a git repo — no watcher expected here")
	case isWatcherAliveForProject(sgRoot, cwd):
		doctorLine("PASS", "watcher (this project)", "alive and bound to this project")
	default:
		doctorLine("WARN", "watcher (this project)", "not running — starts on next sg command / sg watch")
	}

	// --- Engine-side checks via python doctor.py ---
	pyArgs := []string{filepath.Join(sgRoot, "engine", "doctor.py"), sgRoot, cwd}
	if doctorFull {
		pyArgs = append(pyArgs, "--full")
	}
	c := exec.Command(pythonCmd(), pyArgs...)
	c.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8")
	stdout, _ := c.StdoutPipe()
	c.Stderr = os.Stderr
	if err := c.Start(); err != nil {
		doctorLine("FAIL", "engine checks", "could not run engine/doctor.py: "+err.Error())
		os.Exit(1)
	}
	sc := bufio.NewScanner(stdout)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for sc.Scan() {
		parts := strings.SplitN(sc.Text(), "|", 3)
		if len(parts) < 2 {
			continue
		}
		detail := ""
		if len(parts) == 3 {
			detail = parts[2]
		}
		allOK = doctorLine(parts[0], parts[1], detail) && allOK
	}
	_ = c.Wait()

	fmt.Println()
	if allOK {
		fmt.Println(color.New(color.FgGreen).Sprint("  All checks passed."))
		return nil
	}
	fmt.Println(color.New(color.FgRed).Sprint("  Some checks FAILED — see hints above."))
	os.Exit(1)
	return nil
}
