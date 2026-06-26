package cmd

import (
	"fmt"
	"strings"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var scanCmd = &cobra.Command{
	Use:   "scan [text]",
	Short: "Scan text for prompt injection threats",
	Args:  cobra.MinimumNArgs(1),
	RunE:  runScan,
}

func runScan(cmd *cobra.Command, args []string) error {
	text := strings.Join(args, " ")
	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	green := color.New(color.FgGreen).SprintFunc()
	red   := color.New(color.FgRed).SprintFunc()

	escaped := strings.ReplaceAll(text, `\`, `\\`)
	escaped  = strings.ReplaceAll(escaped, "'", `\'`)
	code := fmt.Sprintf(
		`from security import security_scan; threats=security_scan('%s'); `+
		`[print('THREAT:'+t['pattern']) for t in threats] if threats else print('CLEAN')`,
		escaped,
	)

	out, err := runPython(sgRoot, code)
	if err != nil {
		return err
	}

	out = strings.TrimSpace(out)
	if out == "CLEAN" {
		fmt.Printf("%s No threats detected\n", green("[OK]"))
	} else {
		for _, line := range strings.Split(out, "\n") {
			if strings.HasPrefix(line, "THREAT:") {
				fmt.Printf("%s %s\n", red("[THREAT]"), strings.TrimPrefix(line, "THREAT:"))
			}
		}
	}
	return nil
}
