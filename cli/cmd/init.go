package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var initCmd = &cobra.Command{
	Use:   "init",
	Short: "Set up SkillGod in your environment",
	RunE:  runInit,
}

type MCPServer struct {
	Command string            `json:"command"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env"`
}

type MCPConfig struct {
	MCPServers map[string]MCPServer `json:"mcpServers"`
}

func runInit(cmd *cobra.Command, args []string) error {
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	bold   := color.New(color.Bold).SprintFunc()

	fmt.Println(bold("\nSkillGod init"))
	fmt.Println("─────────────────────────────")

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return fmt.Errorf("cannot find skillgod root: %w", err)
	}
	fmt.Printf("  Root:    %s\n", sgRoot)

	dirs := []string{
		filepath.Join(sgRoot, "vault", "instincts"),
		filepath.Join(sgRoot, "vault", "coding"),
		filepath.Join(sgRoot, "vault", "design"),
		filepath.Join(sgRoot, "vault", "writing"),
		filepath.Join(sgRoot, "vault", "devops"),
		filepath.Join(sgRoot, "vault", "security"),
		filepath.Join(sgRoot, "vault", "research"),
		filepath.Join(sgRoot, "vault", "agents"),
		filepath.Join(sgRoot, "vault", "meta"),
		filepath.Join(sgRoot, "db"),
	}
	for _, d := range dirs {
		os.MkdirAll(d, 0755)
	}
	fmt.Printf("  Vault:   %s\n", green("created"))

	enginePath := filepath.Join(sgRoot, "engine", "mcp_server.py")
	mcpConfig := MCPConfig{
		MCPServers: map[string]MCPServer{
			"skillgod": {
				Command: pythonCmd(),
				Args:    []string{enginePath},
				Env: map[string]string{
					"SKILLGOD_PROJECT": filepath.Base(sgRoot),
					"SKILLGOD_ROOT":    sgRoot,
				},
			},
		},
	}

	configBytes, _ := json.MarshalIndent(mcpConfig, "", "  ")

	cwdConfig := filepath.Join(".", ".mcp.json")
	if err := os.WriteFile(cwdConfig, configBytes, 0644); err != nil {
		return fmt.Errorf("failed to write .mcp.json: %w", err)
	}
	fmt.Printf("  .mcp.json: %s\n", green("written to current directory"))

	home, _ := os.UserHomeDir()
	claudeDir := filepath.Join(home, ".claude")
	os.MkdirAll(claudeDir, 0755)
	globalConfig := filepath.Join(claudeDir, ".mcp.json")
	os.WriteFile(globalConfig, configBytes, 0644)
	fmt.Printf("  Global:  %s\n", green(globalConfig))

	fmt.Print("  Index:   rebuilding... ")
	out, err := runPython(sgRoot, "from skills import rebuild_index; n=rebuild_index(); print(n)")
	if err != nil {
		fmt.Printf("%s\n", yellow("skipped (run manually)"))
	} else {
		fmt.Printf("%s skills indexed\n", green(strings.TrimSpace(out)))
	}

	fmt.Println()
	fmt.Println(bold("SkillGod ready."))
	fmt.Println("Restart Claude Code or Antigravity to activate.")
	fmt.Printf("Run %s to verify skills are working.\n", bold("sg stats"))
	return nil
}

func findSkillGodRoot() (string, error) {
	if _, err := os.Stat("engine/mcp_server.py"); err == nil {
		abs, _ := filepath.Abs(".")
		return abs, nil
	}
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	dir := filepath.Dir(exe)
	if _, err := os.Stat(filepath.Join(dir, "engine", "mcp_server.py")); err == nil {
		return dir, nil
	}
	// Walk up from exe directory
	for d := dir; d != filepath.Dir(d); d = filepath.Dir(d) {
		if _, err := os.Stat(filepath.Join(d, "engine", "mcp_server.py")); err == nil {
			return d, nil
		}
	}
	return "", fmt.Errorf("run sg init from your skillgod project directory")
}

func pythonCmd() string {
	if runtime.GOOS == "windows" {
		return "python"
	}
	return "python3"
}

func runPython(root, code string) (string, error) {
	engineDir := filepath.Join(root, "engine")
	c := exec.Command(pythonCmd(),
		"-c",
		fmt.Sprintf("import sys; sys.path.insert(0,r'%s'); %s", engineDir, code),
	)
	c.Dir = root
	out, err := c.Output()
	if err != nil {
		return "", err
	}
	return string(out), nil
}
