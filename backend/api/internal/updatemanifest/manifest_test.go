package updatemanifest

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

var goldenSeed = []byte{
	0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
	16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
}

func TestGoldenManifestCompatibility(t *testing.T) {
	data := mustRead(t, "testdata/golden-manifest.json")
	manifest, err := ParseCanonical(data)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := manifest.CanonicalPayload()
	if err != nil {
		t.Fatal(err)
	}
	if want := bytes.TrimSpace(mustRead(t, "testdata/golden-payload.json")); !bytes.Equal(payload, want) {
		t.Fatalf("canonical payload mismatch\n got: %s\nwant: %s", payload, want)
	}
	publicKey, err := LoadPublicKey("testdata/golden-public-key.pem")
	if err != nil {
		t.Fatal(err)
	}
	if got, want := KeyID(publicKey), "56475aa75463474c"; got != want {
		t.Fatalf("key ID = %q, want %q", got, want)
	}
	if err := manifest.Verify(publicKey, contractTime(t, "2026-08-01T00:00:00Z")); err != nil {
		t.Fatal(err)
	}
	if err := manifest.VerifyArtifact("testdata/golden-artifact.bin"); err != nil {
		t.Fatal(err)
	}
}

func TestSigningMatchesGoldenFixture(t *testing.T) {
	privateKey := ed25519.NewKeyFromSeed(goldenSeed)
	manifest := unsignedGoldenManifest()
	if err := manifest.Sign(privateKey); err != nil {
		t.Fatal(err)
	}
	got, err := manifest.MarshalCanonical()
	if err != nil {
		t.Fatal(err)
	}
	want := bytes.TrimSpace(mustRead(t, "testdata/golden-manifest.json"))
	if !bytes.Equal(got, want) {
		t.Fatalf("signed manifest mismatch\n got: %s\nwant: %s", got, want)
	}
}

func TestVerifyRejectsWrongKeyTamperingAndInvalidTime(t *testing.T) {
	privateKey := ed25519.NewKeyFromSeed(goldenSeed)
	publicKey := privateKey.Public().(ed25519.PublicKey)
	manifest := unsignedGoldenManifest()
	if err := manifest.Sign(privateKey); err != nil {
		t.Fatal(err)
	}

	otherSeed := bytes.Repeat([]byte{0x5a}, ed25519.SeedSize)
	otherKey := ed25519.NewKeyFromSeed(otherSeed).Public().(ed25519.PublicKey)
	if err := manifest.Verify(otherKey, contractTime(t, "2026-08-01T00:00:00Z")); err == nil {
		t.Fatal("wrong public key unexpectedly verified")
	}
	if err := manifest.Verify(publicKey, contractTime(t, "2026-07-27T23:59:59Z")); err == nil {
		t.Fatal("not-yet-valid manifest unexpectedly verified")
	}
	if err := manifest.Verify(publicKey, contractTime(t, "2026-08-27T00:00:01Z")); err == nil {
		t.Fatal("expired manifest unexpectedly verified")
	}
	if err := manifest.Verify(publicKey, contractTime(t, "2026-08-27T00:00:00Z")); err == nil {
		t.Fatal("manifest unexpectedly verified at its exclusive expiry instant")
	}

	manifest.CollectorVersion = "2.3.2"
	if err := manifest.Verify(publicKey, contractTime(t, "2026-08-01T00:00:00Z")); err == nil {
		t.Fatal("tampered manifest unexpectedly verified")
	}
}

func TestParseCanonicalRejectsAlternateRepresentations(t *testing.T) {
	golden := bytes.TrimSpace(mustRead(t, "testdata/golden-manifest.json"))
	cases := map[string][]byte{
		"leading inner whitespace": append([]byte("{ "), golden[1:]...),
		"unknown field": bytes.Replace(
			golden,
			[]byte(`"collector_version"`),
			[]byte(`"extra":true,"collector_version"`),
			1,
		),
		"trailing JSON": append(append([]byte{}, golden...), []byte(` {}`)...),
		"duplicate key": bytes.Replace(
			golden,
			[]byte(`"platform":"linux/amd64"`),
			[]byte(`"platform":"linux/arm64","platform":"linux/amd64"`),
			1,
		),
	}
	for name, data := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := ParseCanonical(data); err == nil {
				t.Fatal("non-canonical manifest unexpectedly parsed")
			}
		})
	}
}

func TestValidationRejectsInvalidContractFields(t *testing.T) {
	validSignature := base64.StdEncoding.EncodeToString(make([]byte, ed25519.SignatureSize))
	cases := map[string]func(*Manifest){
		"schema":       func(m *Manifest) { m.SchemaVersion = 2 },
		"version":      func(m *Manifest) { m.CollectorVersion = "v2.3.1" },
		"minimum":      func(m *Manifest) { m.MinSupportedFromVersion = "2.4.0" },
		"platform":     func(m *Manifest) { m.Platform = "windows/amd64" },
		"digest":       func(m *Manifest) { m.SHA256 = strings.ToUpper(m.SHA256) },
		"empty":        func(m *Manifest) { m.SizeBytes = 0 },
		"oversize":     func(m *Manifest) { m.SizeBytes = MaxArtifactSize + 1 },
		"time format":  func(m *Manifest) { m.NotBefore = "2026-07-28T00:00:00+00:00" },
		"time order":   func(m *Manifest) { m.ExpiresAt = m.NotBefore },
		"validity":     func(m *Manifest) { m.ExpiresAt = "2026-09-01T00:00:00Z" },
		"key ID":       func(m *Manifest) { m.SigningKeyID = "abc" },
		"signature":    func(m *Manifest) { m.Signature = "not-base64" },
		"short sig":    func(m *Manifest) { m.Signature = base64.StdEncoding.EncodeToString([]byte("short")) },
		"prerelease":   func(m *Manifest) { m.CollectorVersion = "2.3.1-rc.1" },
		"other major":  func(m *Manifest) { m.CollectorVersion = "3.0.0" },
		"leading zero": func(m *Manifest) { m.CollectorVersion = "2.03.1" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			manifest := unsignedGoldenManifest()
			manifest.Signature = validSignature
			mutate(&manifest)
			if err := manifest.validate(true); err == nil {
				t.Fatal("invalid manifest unexpectedly validated")
			}
		})
	}
}

func TestArtifactMismatchAndEmptyArtifact(t *testing.T) {
	manifest, err := ParseCanonical(mustRead(t, "testdata/golden-manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "artifact.bin")
	if err := os.WriteFile(path, []byte("tampered"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := manifest.VerifyArtifact(path); err == nil {
		t.Fatal("tampered artifact unexpectedly verified")
	}
	empty := filepath.Join(t.TempDir(), "empty.bin")
	if err := os.WriteFile(empty, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := ArtifactMetadata(empty); err == nil {
		t.Fatal("empty artifact unexpectedly accepted")
	}
}

func TestGenerateAndLoadKeyFiles(t *testing.T) {
	privatePath := filepath.Join(t.TempDir(), "release-private.pem")
	publicPath := filepath.Join(t.TempDir(), "release-public.pem")
	if err := GenerateKeyFiles(privatePath, publicPath); err != nil {
		t.Fatal(err)
	}
	privateKey, err := LoadPrivateKey(privatePath)
	if err != nil {
		t.Fatal(err)
	}
	publicKey, err := LoadPublicKey(publicPath)
	if err != nil {
		t.Fatal(err)
	}
	if !privateKey.Public().(ed25519.PublicKey).Equal(publicKey) {
		t.Fatal("generated keypair does not match")
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(privatePath)
		if err != nil {
			t.Fatal(err)
		}
		if got := info.Mode().Perm(); got != 0o600 {
			t.Fatalf("private key mode = %o, want 600", got)
		}
	}
	if err := GenerateKeyFiles(privatePath, publicPath); err == nil {
		t.Fatal("key generation unexpectedly overwrote existing private key")
	}
}

func TestLoadPrivateKeyRejectsPermissiveModeOnPOSIX(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows does not enforce POSIX mode bits")
	}
	privatePath := filepath.Join(t.TempDir(), "release-private.pem")
	publicPath := filepath.Join(t.TempDir(), "release-public.pem")
	if err := GenerateKeyFiles(privatePath, publicPath); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(privatePath, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadPrivateKey(privatePath); err == nil {
		t.Fatal("permissive private key unexpectedly loaded")
	}
}

func unsignedGoldenManifest() Manifest {
	return Manifest{
		SchemaVersion:           SchemaVersion,
		CollectorVersion:        "2.3.1",
		Platform:                "linux/amd64",
		SHA256:                  "4ee662b3a4aaef43f636a0fe37c36be585d683f62678e8747ceca40c4393caf7",
		SizeBytes:               38,
		NotBefore:               "2026-07-28T00:00:00Z",
		ExpiresAt:               "2026-08-27T00:00:00Z",
		MinSupportedFromVersion: "2.0.0",
		Rollback:                false,
		SigningKeyID:            "56475aa75463474c",
	}
}

func contractTime(t *testing.T, value string) time.Time {
	t.Helper()
	parsed, err := time.Parse("2006-01-02T15:04:05Z", value)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}

func mustRead(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}
