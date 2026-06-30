package cmd

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

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

// IDE targets detected and configured by sg init
type ideTarget struct {
	name    string
	written bool
	note    string
}

func runInit(cmd *cobra.Command, args []string) error {
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	cyan   := color.New(color.FgCyan).SprintFunc()
	dim    := color.New(color.Faint).SprintFunc()
	bold   := color.New(color.Bold).SprintFunc()

	fmt.Println(bold("\nSkillGod init"))

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return fmt.Errorf("cannot find skillgod root: %w", err)
	}

	// ── Create vault directories (quietly) ─────────────────────────────────
	for _, d := range []string{
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
	} {
		os.MkdirAll(d, 0755)
	}

	// ── Detect installed IDEs ──────────────────────────────────────────────
	detected := detectIDEs()
	if len(detected) > 0 {
		for _, d := range detected {
			fmt.Printf("  %s %s detected %s\n", green("✓"), d.name, dim("("+d.note+")"))
		}
	} else {
		fmt.Printf("  %s No IDE auto-detected — writing config to current dir\n", yellow("○"))
	}

	// ── Write configs for all supported tools ──────────────────────────────
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
	writeIDEConfigs(sgRoot, configBytes, green, yellow)
	fmt.Printf("  %s .mcp.json written\n", green("✓"))

	// ── Rebuild skill index (timed) ────────────────────────────────────────
	t0 := time.Now()
	indexOut, indexErr := runPython(sgRoot, "from skills import rebuild_index; n=rebuild_index(); print(n)")
	secs := time.Since(t0).Seconds()
	skillCount := strings.TrimSpace(indexOut)
	if indexErr != nil {
		fmt.Printf("  %s index skipped — run %s\n", yellow("○"), bold("sg stats"))
		skillCount = "0"
	} else {
		fmt.Printf("  %s %s skills indexed in %.1fs\n",
			green("✓"), green(skillCount), secs)
	}

	// ── Live preview: show skills firing for a real task ───────────────────
	demoTask := "build a React component"
	demoCode := fmt.Sprintf(
		`from skills import find_skills;`+
		`r=find_skills('%s', top_k=3);`+
		`[print(f"{x['score']:.2f}|{x['name']}|{' '.join(x.get('matched',[]))[:28]}") for x in r]`,
		demoTask,
	)
	if demoOut, err := runPython(sgRoot, demoCode); err == nil {
		var demoLines []string
		for _, line := range strings.Split(strings.TrimSpace(demoOut), "\n") {
			line = strings.TrimSpace(line)
			if line != "" {
				demoLines = append(demoLines, line)
			}
		}
		if len(demoLines) > 0 {
			fmt.Println()
			fmt.Printf("  %s  %s\n",
				bold("Preview:"),
				dim(fmt.Sprintf(`sg find "%s"`, demoTask)),
			)
			for _, line := range demoLines {
				parts := strings.SplitN(line, "|", 3)
				if len(parts) == 3 {
					fmt.Printf("    %-24s %s  %s\n",
						bold(parts[1]),
						green(parts[0]),
						cyan(parts[2]),
					)
				}
			}
			fmt.Printf("  %s\n", dim("These fire automatically before your AI sees your prompt."))
		}
	}

	// ── Next steps ──────────────────────────────────────────────────────────
	fmt.Println()
	fmt.Printf("  %s\n", bold("What's active:"))
	if skillCount != "0" && skillCount != "" {
		fmt.Printf("    %s  %s skills scored per task, top 3 injected\n", green("✓"), green(skillCount))
	}
	fmt.Printf("    %s  always-on instincts — no scoring needed\n", green("✓"))
	fmt.Printf("    %s  git-aware session memory\n", green("✓"))
	fmt.Printf("    %s  MCP server on localhost:3333\n", green("✓"))

	fmt.Println()
	target := "your IDE"
	if len(detected) > 0 {
		target = detected[0].name
	}
	fmt.Printf("Restart %s to activate.\n\n", cyan(target))
	fmt.Printf("  %s  see what fires for your task\n", bold("sg find \"<your task>\""))
	fmt.Printf("  %s      memory timeline for this project\n", bold("sg timeline"))
	fmt.Printf("  %s         vault health + usage stats\n", bold("sg stats"))
	fmt.Println()
	return nil
}

// detectIDEs returns the IDEs/tools actually present on this machine.
func detectIDEs() []ideTarget {
	home, _ := os.UserHomeDir()
	cwd, _  := os.Getwd()

	short := func(p string) string {
		if home != "" && strings.HasPrefix(p, home) {
			return "~" + p[len(home):]
		}
		return p
	}

	checks := []struct{ name, path string }{
		{"Cursor", filepath.Join(home, ".cursor")},
		{"Claude Code", filepath.Join(home, ".claude")},
		{"Windsurf", filepath.Join(home, ".codeium", "windsurf")},
		{"Antigravity", filepath.Join(home, ".antigravity")},
		{"Continue (Ollama)", filepath.Join(home, ".continue")},
		{"VS Code", filepath.Join(cwd, ".vscode")},
	}

	var found []ideTarget
	for _, c := range checks {
		if c.path == "" {
			continue
		}
		if _, err := os.Stat(c.path); err == nil {
			found = append(found, ideTarget{name: c.name, written: true, note: short(c.path)})
		}
	}
	return found
}

// writeIDEConfigs writes config files for every supported IDE/tool.
// Returns a slice of targets with written status and notes.
func writeIDEConfigs(sgRoot string, mcpBytes []byte, green, yellow func(...interface{}) string) []ideTarget {
	var targets []ideTarget
	home, _ := os.UserHomeDir()
	cwd, _  := os.Getwd()

	// ── 1. .mcp.json (Claude Code, Cursor, Antigravity, Windsurf) ──────────
	cwdMCP := filepath.Join(cwd, ".mcp.json")
	err    := os.WriteFile(cwdMCP, mcpBytes, 0644)
	targets = append(targets, ideTarget{
		name:    "Claude Code",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})
	targets = append(targets, ideTarget{
		name:    "Cursor",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})
	targets = append(targets, ideTarget{
		name:    "Antigravity",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})
	targets = append(targets, ideTarget{
		name:    "Windsurf",
		written: err == nil,
		note:    ".mcp.json → current dir",
	})

	// Also write to ~/.claude/.mcp.json for global Claude Code
	claudeDir := filepath.Join(home, ".claude")
	os.MkdirAll(claudeDir, 0755)
	os.WriteFile(filepath.Join(claudeDir, ".mcp.json"), mcpBytes, 0644)

	// ── 2. GitHub Copilot (.github/copilot-instructions.md) ─────────────────
	// GitHub Copilot reads this file and injects it into every session.
	// Works in VS Code, JetBrains, Neovim, vim with Copilot plugin.
	githubDir := filepath.Join(cwd, ".github")
	os.MkdirAll(githubDir, 0755)
	copilotInstructions := buildCopilotInstructions(sgRoot)
	copilotPath := filepath.Join(githubDir, "copilot-instructions.md")
	copilotErr  := os.WriteFile(copilotPath, []byte(copilotInstructions), 0644)
	targets = append(targets, ideTarget{
		name:    "GitHub Copilot",
		written: copilotErr == nil,
		note:    ".github/copilot-instructions.md",
	})

	// ── 3. Ollama / Continue.dev (~/.continue/config.json) ──────────────────
	// Continue.dev is the most popular Ollama IDE integration.
	// It reads ~/.continue/config.json and supports custom system prompts.
	continueDir := filepath.Join(home, ".continue")
	os.MkdirAll(continueDir, 0755)
	continueConfigPath := filepath.Join(continueDir, "config.json")
	continueErr := writeContinueConfig(sgRoot, continueConfigPath)
	targets = append(targets, ideTarget{
		name:    "Ollama (Continue)",
		written: continueErr == nil,
		note:    "~/.continue/config.json",
	})

	// ── 4. VS Code settings (Codex / GitHub Copilot workspace settings) ─────
	vscodeDir := filepath.Join(cwd, ".vscode")
	if _, err := os.Stat(vscodeDir); err == nil {
		// .vscode exists — write workspace settings to enable Copilot instructions
		settingsPath := filepath.Join(vscodeDir, "settings.json")
		vsErr := writeVSCodeSettings(settingsPath)
		targets = append(targets, ideTarget{
			name:    "VS Code (Codex)",
			written: vsErr == nil,
			note:    ".vscode/settings.json updated",
		})
	} else {
		targets = append(targets, ideTarget{
			name:    "VS Code (Codex)",
			written: false,
			note:    "no .vscode/ found — open in VS Code first",
		})
	}

	return targets
}

// buildCopilotInstructions returns the content for .github/copilot-instructions.md
func buildCopilotInstructions(sgRoot string) string {
	return `# SkillGod — Active Coding Standards

> Auto-generated by SkillGod (sg init). Do not edit manually — run sg init to regenerate.

## What SkillGod Does

SkillGod injects 1,944 curated skills and project memory into every AI coding session.
These instructions are the static fallback for GitHub Copilot (which does not support MCP).
For full live injection, use Claude Code or Cursor with sg init.

## Core Rules (always apply)

- Always verify output matches the request before saying done
- Never modify files in vault/ directly — use sg learn or vault/meta/
- Validate inputs before any database write
- Use absolute imports, not relative
- Check error returns — never silently ignore them
- Write tests for anything that could break in production

## Memory

Project decisions, patterns, and errors are stored by SkillGod memory.
Key decisions from previous sessions will be injected at session start when using a supported IDE.

## Skill Vault

This project has access to 1,944 curated skills across:
- coding/ — Python, TypeScript, React, debugging, code review
- design/ — UI/UX, layout, Figma, brutalist patterns
- devops/ — Docker, Railway, Vercel, CI/CD
- security/ — OWASP, injection detection, auth patterns
- agents/ — multi-agent orchestration, MCP, swarm patterns
- writing/ — docs, README, blog, API documentation

Run ` + "`sg find <task>`" + ` to see which skills apply to your current task.
Run ` + "`sg stats`" + ` to see vault health and memory stats.
`
}

// writeContinueConfig writes or merges SkillGod config into ~/.continue/config.json
func writeContinueConfig(sgRoot, configPath string) error {
	// Read existing config if present
	existing := map[string]interface{}{}
	if data, err := os.ReadFile(configPath); err == nil {
		json.Unmarshal(data, &existing)
	}

	// SkillGod system message for Ollama sessions
	systemMsg := `You are working with SkillGod active. SkillGod provides:
- 1,944 curated coding skills injected based on task relevance
- Persistent memory of project decisions, patterns, and errors
- Security scanning on all inputs

Core rules:
- Always verify output matches the request before saying done
- Validate inputs before database writes
- Use absolute imports
- Never silently ignore errors

Run sg find <task> in terminal to see relevant skills for your current task.
Run sg stats to check vault and memory status.`

	existing["systemMessage"] = systemMsg

	// Ensure tabAutocompleteModel is set if not already configured
	if _, ok := existing["tabAutocompleteModel"]; !ok {
		existing["tabAutocompleteModel"] = nil
	}

	// Tag with SkillGod version marker
	existing["_skillgod"] = map[string]string{
		"managed_by": "sg init",
		"version":    "1.0.0",
	}

	out, err := json.MarshalIndent(existing, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(configPath, out, 0644)
}

// writeVSCodeSettings enables Copilot workspace-level instructions in VS Code
func writeVSCodeSettings(settingsPath string) error {
	existing := map[string]interface{}{}
	if data, err := os.ReadFile(settingsPath); err == nil {
		json.Unmarshal(data, &existing)
	}

	// Enable GitHub Copilot to use .github/copilot-instructions.md
	existing["github.copilot.chat.codeGeneration.useInstructionFiles"] = true
	existing["github.copilot.chat.reviewSelection.useInstructionFiles"] = true

	out, err := json.MarshalIndent(existing, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(settingsPath, out, 0644)
}

// isSkillGodRoot reports whether dir contains the SkillGod engine.
func isSkillGodRoot(dir string) bool {
	_, err := os.Stat(filepath.Join(dir, "engine", "mcp_server.py"))
	return err == nil
}

// findSkillGodRoot locates the installed engine + vault. For users who
// installed via the one-line installer, this lives in ~/.skillgod (the
// installer unpacks the engine bundle there). Developers running from a
// source checkout resolve to the repo via the cwd / parent-walk checks.
func findSkillGodRoot() (string, error) {
	// 1. Explicit override — highest priority.
	if env := os.Getenv("SKILLGOD_HOME"); env != "" && isSkillGodRoot(env) {
		return env, nil
	}

	// 2. Current dir (developer running inside the source repo).
	if isSkillGodRoot(".") {
		abs, _ := filepath.Abs(".")
		return abs, nil
	}

	// 3. Installed location — ~/.skillgod (the installer's target).
	if home, err := os.UserHomeDir(); err == nil {
		root := filepath.Join(home, ".skillgod")
		if isSkillGodRoot(root) {
			return root, nil
		}
	}

	// 4. Next to the binary, then walk up its parents.
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		for d := dir; d != filepath.Dir(d); d = filepath.Dir(d) {
			if isSkillGodRoot(d) {
				return d, nil
			}
		}
	}

	return "", fmt.Errorf("SkillGod engine not found in ~/.skillgod — reinstall from https://skillgod.dev/download, or set SKILLGOD_HOME to your engine directory")
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
