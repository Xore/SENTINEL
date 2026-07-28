package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCLIKeygenSignVerifyRoundTrip(t *testing.T) {
	temp := t.TempDir()
	privatePath := filepath.Join(temp, "release-private.pem")
	publicPath := filepath.Join(temp, "release-public.pem")
	artifactPath := filepath.Join(temp, "collector")
	manifestPath := filepath.Join(temp, "manifest.json")
	if err := os.WriteFile(artifactPath, []byte("collector release artifact"), 0o600); err != nil {
		t.Fatal(err)
	}

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if err := run(
		[]string{
			"keygen",
			"--private-key", privatePath,
			"--public-key", publicPath,
		},
		&stdout,
		&stderr,
	); err != nil {
		t.Fatalf("keygen: %v\nstderr: %s", err, stderr.String())
	}
	if !strings.Contains(stdout.String(), "generated Ed25519 release key") {
		t.Fatalf("unexpected keygen output: %s", stdout.String())
	}

	stdout.Reset()
	stderr.Reset()
	if err := run(
		[]string{
			"sign",
			"--artifact", artifactPath,
			"--collector-version", "2.4.0",
			"--platform", "linux/arm64",
			"--not-before", "2026-07-28T00:00:00Z",
			"--expires-at", "2026-08-20T00:00:00Z",
			"--min-supported-from-version", "2.0.0",
			"--private-key", privatePath,
			"--output", manifestPath,
		},
		&stdout,
		&stderr,
	); err != nil {
		t.Fatalf("sign: %v\nstderr: %s", err, stderr.String())
	}

	stdout.Reset()
	stderr.Reset()
	if err := run(
		[]string{
			"verify",
			"--manifest", manifestPath,
			"--artifact", artifactPath,
			"--public-key", publicPath,
			"--at", "2026-08-01T00:00:00Z",
		},
		&stdout,
		&stderr,
	); err != nil {
		t.Fatalf("verify: %v\nstderr: %s", err, stderr.String())
	}
	if !strings.Contains(stdout.String(), "verified collector 2.4.0 for linux/arm64") {
		t.Fatalf("unexpected verify output: %s", stdout.String())
	}
}

func TestCLIDoesNotOverwriteManifest(t *testing.T) {
	temp := t.TempDir()
	privatePath := filepath.Join(temp, "release-private.pem")
	publicPath := filepath.Join(temp, "release-public.pem")
	artifactPath := filepath.Join(temp, "collector")
	manifestPath := filepath.Join(temp, "manifest.json")
	if err := os.WriteFile(artifactPath, []byte("collector release artifact"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := run(
		[]string{"keygen", "--private-key", privatePath, "--public-key", publicPath},
		&bytes.Buffer{},
		&bytes.Buffer{},
	); err != nil {
		t.Fatal(err)
	}
	args := []string{
		"sign",
		"--artifact", artifactPath,
		"--collector-version", "2.4.0",
		"--platform", "linux/amd64",
		"--not-before", "2026-07-28T00:00:00Z",
		"--expires-at", "2026-08-20T00:00:00Z",
		"--min-supported-from-version", "2.0.0",
		"--private-key", privatePath,
		"--output", manifestPath,
	}
	if err := run(args, &bytes.Buffer{}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	if err := run(args, &bytes.Buffer{}, &bytes.Buffer{}); err == nil {
		t.Fatal("sign unexpectedly overwrote an existing manifest")
	}
}
