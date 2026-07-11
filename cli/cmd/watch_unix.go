//go:build !windows

package cmd

import (
	"os/exec"
	"syscall"
)

// applyDetachAttrs starts the child in its own session (setsid) so it isn't
// tied to this process's controlling terminal — it won't receive SIGHUP when
// the launching shell exits or the terminal closes.
func applyDetachAttrs(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}

// isProcessAlive uses the standard Unix idiom: signal 0 performs permission/
// existence checks without actually sending a signal.
func isProcessAlive(pid int) bool {
	err := syscall.Kill(pid, syscall.Signal(0))
	return err == nil
}
