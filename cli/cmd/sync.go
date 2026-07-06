package cmd

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
)

var licenseKey string

var syncCmd = &cobra.Command{
	Use:   "sync",
	Short: "Sync vault with latest skills",
	Long: `Sync your skill vault.

Free tier:  sg sync                          (indexes local vault, 30 starter skills)
Pro tier:   sg sync --key YOUR_LICENSE_KEY   (decrypts full vault, 1,927 skills active)`,
	RunE: runSync,
}

func init() {
	syncCmd.Flags().StringVar(&licenseKey, "key", "", "License key for pro vault")
}

func runSync(cmd *cobra.Command, args []string) error {
	green  := color.New(color.FgGreen).SprintFunc()
	yellow := color.New(color.FgYellow).SprintFunc()
	red    := color.New(color.FgRed).SprintFunc()
	bold   := color.New(color.Bold).SprintFunc()

	sgRoot, err := findSkillGodRoot()
	if err != nil {
		return err
	}

	if licenseKey == "" {
		// Free tier — index local vault
		fmt.Println(bold("Syncing free tier (30 starter skills)..."))
		fmt.Println(yellow("Upgrade to Pro for 1,927+ skills: skillgod.dev"))
		out, _ := runPython(sgRoot, "from skills import rebuild_index; print(rebuild_index())")
		fmt.Printf("Index updated: %s skills\n", green(strings.TrimSpace(out)))
		return nil
	}

	// Coupon code — route to redeem
	if strings.HasPrefix(strings.ToUpper(licenseKey), "SKILL-") {
		fmt.Println("Coupon code detected — redeeming...")
		return runRedeem(cmd, []string{licenseKey})
	}

	// ── Pro tier: full encrypted vault sync ──────────────────────────────
	fmt.Println(bold("Validating license key..."))

	// Step 0: if no local encrypted vault can be decrypted by this key, fetch a
	// per-machine encrypted vault from the server (fixes the "vault keyed to one
	// machine" problem — every customer gets a vault only they can decrypt).
	escaped := strings.ReplaceAll(licenseKey, "'", `\'`)
	preVerify, _ := runPython(sgRoot,
		fmt.Sprintf(`from encryption import verify_key; print(verify_key('%s'))`, escaped))
	if strings.TrimSpace(preVerify) != "True" {
		// Prefer the R2/CDN path (one static zip, downloaded direct from R2).
		// Fall back to per-machine server encryption if R2 isn't configured.
		if fetched := fetchVaultFromR2(sgRoot, licenseKey, green, yellow); fetched {
			fmt.Printf("  %s Vault downloaded from CDN for this machine\n", green("[OK]"))
		} else if fetched := fetchVaultFromServer(sgRoot, licenseKey, green, yellow); fetched {
			fmt.Printf("  %s Vault downloaded for this machine\n", green("[OK]"))
		}
	}

	// Step 1: verify key can decrypt sentinel
	verifyCode := fmt.Sprintf(
		`from encryption import verify_key; print(verify_key('%s'))`,
		escaped,
	)
	verifyOut, verifyErr := runPython(sgRoot, verifyCode)
	verifyOut = strings.TrimSpace(verifyOut)

	// If vault_encrypted/ doesn't exist yet, validate via LemonSqueezy instead
	if verifyErr != nil || verifyOut == "" {
		// Fall back to LemonSqueezy license check
		lsCode := fmt.Sprintf(
			`from license import check_license; check_license('%s')`,
			escaped,
		)
		lsOut, lsErr := runPython(sgRoot, lsCode)
		if lsErr != nil {
			fmt.Printf("%s License validation error: %v\n", red("[ERROR]"), lsErr)
			fmt.Println("Check your internet connection or run: sg sync --key KEY")
			return nil
		}
		lsOut = strings.TrimSpace(lsOut)
		if !strings.HasPrefix(lsOut, "LICENSE_VALID:") {
			reason := strings.TrimPrefix(lsOut, "LICENSE_INVALID:")
			fmt.Printf("%s Invalid license key\n", red("[BLOCKED]"))
			if reason != "" {
				fmt.Printf("  Reason: %s\n", reason)
			}
			fmt.Println()
			fmt.Println("  Purchase a license at: skillgod.dev")
			return nil
		}
		fmt.Printf("%s License valid (online verified)\n", green("[OK]"))
	} else if verifyOut == "False" {
		fmt.Printf("%s Invalid license key — cannot decrypt vault\n", red("[BLOCKED]"))
		fmt.Println("  Purchase a license at: skillgod.dev")
		fmt.Println("  Free tier: sg sync  (no key needed)")
		return nil
	} else {
		fmt.Printf("%s License key valid\n", green("[OK]"))
	}

	// Step 2: decrypt full vault in memory and write to vault/
	fmt.Println()
	fmt.Println(bold("Decrypting vault..."))
	syncCode := fmt.Sprintf(
		`from encryption import sync_encrypted_vault; `+
		`from skills import rebuild_index; `+
		`n = sync_encrypted_vault('%s'); `+
		`idx = rebuild_index(); `+
		`print(f"SYNCED:{n}:{idx}")`,
		escaped,
	)
	syncOut, syncErr := runPython(sgRoot, syncCode)
	if syncErr != nil {
		fmt.Printf("%s Vault decrypt failed: %v\n", red("[ERROR]"), syncErr)
		fmt.Println("  Is vault_encrypted/ present? Run: python engine/encryption.py encrypt --key KEY")
		return nil
	}

	syncOut = strings.TrimSpace(syncOut)
	if strings.HasPrefix(syncOut, "SYNCED:") {
		parts := strings.Split(strings.TrimPrefix(syncOut, "SYNCED:"), ":")
		written := parts[0]
		indexed := ""
		if len(parts) > 1 {
			indexed = parts[1]
		}
		fmt.Printf("  Vault synced: %s skills active\n", green(indexed))
		fmt.Printf("  Files written: %s\n", green(written))
		fmt.Println()
		fmt.Printf("%s Full vault active. Skills injecting at every prompt.\n", green("[OK]"))
	} else {
		fmt.Printf("%s Unexpected sync output: %s\n", yellow("[warn]"), syncOut)
	}

	// ── Check for monthly vault updates ────────────────────────────────────
	checkVaultUpdate(green, yellow)

	return nil
}

// fetchVaultFromServer downloads a vault encrypted to THIS machine's
// (license_key, machine_id) and writes the .sg blobs into vault_encrypted/.
// Returns true on success. The caller then decrypts locally with the same key.
func fetchVaultFromServer(sgRoot, key string, green, yellow func(...interface{}) string) bool {
	apiURL := os.Getenv("SKILLGOD_API")
	if apiURL == "" {
		apiURL = "https://api.skillgod.dev"
	}

	// BUG-009 FIX — send the CANONICAL (hashed) machine id, matching what license
	// validation stores in pro_licenses.machine_id. Previously this used
	// encryption.get_machine_id() (the RAW id), so the vault endpoints bound a
	// different identity than validation expected.
	mid, _ := runPython(sgRoot, "from license import get_canonical_machine_id; print(get_canonical_machine_id())")
	iid, _ := runPython(sgRoot, "from license import get_install_id; print(get_install_id())")
	mid = strings.TrimSpace(mid)
	iid = strings.TrimSpace(iid)
	if mid == "" {
		return false
	}

	body, _ := json.Marshal(map[string]string{
		"key": key, "machine_id": mid, "install_id": iid,
	})
	req, err := http.NewRequest("POST",
		strings.TrimRight(apiURL, "/")+"/v1/vault/fetch", bytes.NewReader(body))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 90 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		fmt.Printf("  %s could not reach vault server\n", yellow("[warn]"))
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return false
	}

	var payload struct {
		Count int               `json:"count"`
		Files map[string]string `json:"files"`
	}
	if json.NewDecoder(resp.Body).Decode(&payload) != nil || len(payload.Files) == 0 {
		return false
	}

	encDir := filepath.Join(sgRoot, "vault_encrypted")
	written := 0
	for rel, b64 := range payload.Files {
		raw, derr := base64.StdEncoding.DecodeString(b64)
		if derr != nil {
			continue
		}
		dest := filepath.Join(encDir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(dest), 0755); err != nil {
			continue
		}
		if os.WriteFile(dest, raw, 0644) == nil {
			written++
		}
	}
	return written > 0
}

// fetchVaultFromR2 downloads the static, release-key-encrypted vault_pro.zip
// directly from R2 (via a presigned URL the API signs), then has the python
// engine unwrap the per-machine release key and install vault_encrypted/.
// Returns true on success, false if the R2 path isn't available (caller then
// falls back to the per-machine /v1/vault/fetch path).
func fetchVaultFromR2(sgRoot, key string, green, yellow func(...interface{}) string) bool {
	apiURL := os.Getenv("SKILLGOD_API")
	if apiURL == "" {
		apiURL = "https://api.skillgod.dev"
	}

	// BUG-009 FIX — canonical (hashed) machine id, see fetchVaultFromServer.
	mid, _ := runPython(sgRoot, "from license import get_canonical_machine_id; print(get_canonical_machine_id())")
	mid = strings.TrimSpace(mid)
	if mid == "" {
		return false
	}

	// 1. Ask the API for a presigned R2 URL + the release key wrapped to us.
	req, err := http.NewRequest("GET", strings.TrimRight(apiURL, "/")+"/v1/vault/signed-url", nil)
	if err != nil {
		return false
	}
	req.Header.Set("X-License-Key", key)
	req.Header.Set("X-Machine-Id", mid)

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil || resp.StatusCode != 200 {
		if resp != nil {
			resp.Body.Close()
		}
		return false // not configured / no entitlement — fall back
	}
	var meta struct {
		URL               string `json:"url"`
		Version           string `json:"version"`
		WrappedReleaseKey string `json:"wrapped_release_key"`
		Sha256            string `json:"sha256"`
	}
	derr := json.NewDecoder(resp.Body).Decode(&meta)
	resp.Body.Close()
	if derr != nil || meta.URL == "" || meta.WrappedReleaseKey == "" {
		return false // no zip/key available — fall back to per-machine fetch
	}

	// 2. Download the zip straight from R2, hashing it as it streams in.
	zresp, err := (&http.Client{Timeout: 180 * time.Second}).Get(meta.URL)
	if err != nil || zresp.StatusCode != 200 {
		if zresp != nil {
			zresp.Body.Close()
		}
		fmt.Printf("  %s could not download vault from CDN\n", yellow("[warn]"))
		return false
	}
	defer zresp.Body.Close()

	tmp, err := os.CreateTemp("", "vault_pro_*.zip")
	if err != nil {
		return false
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	hasher := sha256.New()
	if _, err := io.Copy(io.MultiWriter(tmp, hasher), zresp.Body); err != nil {
		tmp.Close()
		return false
	}
	tmp.Close()

	// BUG-029 — verify the zip's SHA256 BEFORE handing it to the decryptor. A
	// corrupted/truncated R2 object otherwise surfaces as a cryptic decryption
	// error; this gives a clear, actionable message and avoids a bad install.
	if meta.Sha256 != "" {
		got := hex.EncodeToString(hasher.Sum(nil))
		if !strings.EqualFold(got, meta.Sha256) {
			fmt.Printf("  %s Vault download corrupted (checksum mismatch) — please retry: sg sync --key YOUR_KEY\n", yellow("[ERROR]"))
			return false
		}
	}

	// 3. Hand the zip + wrapped key to the engine: unwrap K_rel, decrypt, and
	//    re-encrypt under this machine's key into vault_encrypted/.
	escKey := strings.ReplaceAll(key, "'", `\'`)
	escWrap := strings.ReplaceAll(meta.WrappedReleaseKey, "'", `\'`)
	escZip := strings.ReplaceAll(filepath.ToSlash(tmpPath), "'", `\'`)
	installCode := fmt.Sprintf(
		`from encryption import install_release_zip; `+
			`print(install_release_zip('%s', '%s', '%s'))`,
		escZip, escWrap, escKey,
	)
	out, ierr := runPython(sgRoot, installCode)
	if ierr != nil {
		return false
	}
	out = strings.TrimSpace(out)
	return out != "" && out != "0"
}

// checkVaultUpdate pings /v1/vault/latest to see if a newer vault exists.
// Silently skips if SKILLGOD_API or SKILLGOD_API_SECRET env vars are not set.
func checkVaultUpdate(green, yellow func(...interface{}) string) {
	apiURL    := os.Getenv("SKILLGOD_API")
	apiSecret := os.Getenv("SKILLGOD_API_SECRET")
	if apiURL == "" || apiSecret == "" {
		return
	}

	client := &http.Client{Timeout: 6 * time.Second}
	req, err := http.NewRequest("GET", strings.TrimRight(apiURL, "/")+"/v1/vault/latest", nil)
	if err != nil {
		return
	}
	req.Header.Set("x-api-key", apiSecret)

	resp, err := client.Do(req)
	if err != nil || resp.StatusCode != 200 {
		return
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var release struct {
		Version      string `json:"version"`
		TotalSkills  int    `json:"total_skills"`
		SkillsAdded  int    `json:"skills_added"`
		DownloadURL  string `json:"download_url"`
		ReleaseNotes string `json:"release_notes"`
		ReleasedAt   string `json:"released_at"`
	}
	if json.Unmarshal(body, &release) != nil || release.Version == "" {
		return
	}

	// Compare with local version from kv store (if tracked)
	localVer, _ := runPython("", "from skills import vault_version; print(vault_version())")
	localVer = strings.TrimSpace(localVer)

	if localVer != "" && localVer == release.Version {
		fmt.Printf("  Vault version: %s (up to date)\n", green(release.Version))
		return
	}

	fmt.Println()
	fmt.Printf("  %s New vault release available: %s\n", yellow("↑"), yellow(release.Version))
	if release.SkillsAdded > 0 {
		fmt.Printf("    %d new skills added\n", release.SkillsAdded)
	}
	if release.ReleaseNotes != "" {
		fmt.Printf("    %s\n", release.ReleaseNotes)
	}
	if release.DownloadURL != "" {
		fmt.Printf("    Download: %s\n", release.DownloadURL)
	}
	fmt.Printf("  Run %s to update.\n", "sg sync --key <YOUR_KEY>")
}
