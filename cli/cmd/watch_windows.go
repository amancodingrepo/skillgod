//go:build windows

package cmd

import (
	"os/exec"
	"syscall"

	"golang.org/x/sys/windows"
)

// applyDetachAttrs detaches the child from this console so it survives both
// this CLI process exiting AND the terminal window closing. Without
// DETACHED_PROCESS, a console-attached child receives CTRL_CLOSE_EVENT when
// the launching console closes and Windows terminates it — defeating the
// entire point of a background watcher.
//
// CREATE_NO_WINDOW is also required — DETACHED_PROCESS alone does not
// reliably suppress the console for a console-subsystem child (python.exe):
// Windows can still briefly flash a conhost.exe window at spawn time.
// Confirmed via live testing on this machine (visible conhost flashes in
// Task Manager, one per self-heal spawn, until this flag was added).
func applyDetachAttrs(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: windows.CREATE_NEW_PROCESS_GROUP | windows.DETACHED_PROCESS | windows.CREATE_NO_WINDOW,
	}
}

// isProcessAlive uses a real OpenProcess handle rather than os.FindProcess
// (which on Windows always "succeeds" regardless of whether the PID exists —
// it does no verification, so it can't be used as a liveness check here).
func isProcessAlive(pid int) bool {
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return false
	}
	defer windows.CloseHandle(h)

	var exitCode uint32
	if err := windows.GetExitCodeProcess(h, &exitCode); err != nil {
		return false
	}
	const stillActive = 259 // STILL_ACTIVE
	return exitCode == stillActive
}
