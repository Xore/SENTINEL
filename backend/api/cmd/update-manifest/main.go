// Command update-manifest is the offline release-engineering utility for
// generating Ed25519 keys and signing/verifying collector update manifests.
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/Xore/analyseLaptop/backend/api/internal/updatemanifest"
)

const contractTimeLayout = "2006-01-02T15:04:05Z"

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "update-manifest:", err)
		os.Exit(1)
	}
}

func run(args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		printUsage(stderr)
		return errors.New("a subcommand is required")
	}
	switch args[0] {
	case "keygen":
		return runKeygen(args[1:], stdout, stderr)
	case "sign":
		return runSign(args[1:], stdout, stderr)
	case "verify":
		return runVerify(args[1:], stdout, stderr)
	default:
		printUsage(stderr)
		return fmt.Errorf("unknown subcommand %q", args[0])
	}
}

func runKeygen(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("keygen", flag.ContinueOnError)
	flags.SetOutput(stderr)
	privatePath := flags.String("private-key", "", "new PKCS#8 Ed25519 private-key PEM path")
	publicPath := flags.String("public-key", "", "new PKIX Ed25519 public-key PEM path")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 || *privatePath == "" || *publicPath == "" {
		return errors.New("keygen requires --private-key and --public-key")
	}
	if err := updatemanifest.GenerateKeyFiles(*privatePath, *publicPath); err != nil {
		return err
	}
	publicKey, err := updatemanifest.LoadPublicKey(*publicPath)
	if err != nil {
		return err
	}
	fmt.Fprintf(stdout, "generated Ed25519 release key %s\n", updatemanifest.KeyID(publicKey))
	return nil
}

func runSign(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("sign", flag.ContinueOnError)
	flags.SetOutput(stderr)
	artifactPath := flags.String("artifact", "", "collector artifact to hash and sign")
	version := flags.String("collector-version", "", "stable v2 version, for example 2.3.1")
	platform := flags.String("platform", "", "linux/amd64 or linux/arm64")
	notBefore := flags.String("not-before", "", "UTC RFC3339 seconds")
	expiresAt := flags.String("expires-at", "", "UTC RFC3339 seconds")
	minVersion := flags.String("min-supported-from-version", "", "oldest installable v2 version")
	privatePath := flags.String("private-key", "", "PKCS#8 Ed25519 private-key PEM")
	outputPath := flags.String("output", "", "new canonical manifest JSON path")
	rollback := flags.Bool("rollback", false, "authorize an explicit downgrade")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 ||
		*artifactPath == "" ||
		*version == "" ||
		*platform == "" ||
		*notBefore == "" ||
		*expiresAt == "" ||
		*minVersion == "" ||
		*privatePath == "" ||
		*outputPath == "" {
		return errors.New("sign requires artifact, version, platform, validity, minimum version, key, and output")
	}
	size, digest, err := updatemanifest.ArtifactMetadata(*artifactPath)
	if err != nil {
		return err
	}
	privateKey, err := updatemanifest.LoadPrivateKey(*privatePath)
	if err != nil {
		return err
	}
	manifest := updatemanifest.Manifest{
		SchemaVersion:           updatemanifest.SchemaVersion,
		CollectorVersion:        *version,
		Platform:                *platform,
		SHA256:                  digest,
		SizeBytes:               size,
		NotBefore:               *notBefore,
		ExpiresAt:               *expiresAt,
		MinSupportedFromVersion: *minVersion,
		Rollback:                *rollback,
	}
	if err := manifest.Sign(privateKey); err != nil {
		return err
	}
	encoded, err := manifest.MarshalCanonical()
	if err != nil {
		return err
	}
	if err := writeNewFile(*outputPath, append(encoded, '\n'), 0o644); err != nil {
		return err
	}
	fmt.Fprintf(
		stdout,
		"signed %s (%d bytes, %s) with key %s\n",
		*artifactPath,
		size,
		digest,
		manifest.SigningKeyID,
	)
	return nil
}

func runVerify(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("verify", flag.ContinueOnError)
	flags.SetOutput(stderr)
	manifestPath := flags.String("manifest", "", "canonical manifest JSON")
	artifactPath := flags.String("artifact", "", "collector artifact")
	publicPath := flags.String("public-key", "", "PKIX Ed25519 public-key PEM")
	at := flags.String("at", "", "verification time in UTC RFC3339 seconds; defaults to now")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 || *manifestPath == "" || *artifactPath == "" || *publicPath == "" {
		return errors.New("verify requires --manifest, --artifact, and --public-key")
	}
	now := time.Now().UTC()
	if *at != "" {
		var err error
		now, err = time.Parse(contractTimeLayout, *at)
		if err != nil || now.Format(contractTimeLayout) != *at {
			return errors.New("--at must use exact UTC RFC3339 seconds")
		}
	}
	data, err := os.ReadFile(*manifestPath)
	if err != nil {
		return fmt.Errorf("read manifest: %w", err)
	}
	manifest, err := updatemanifest.ParseCanonical(data)
	if err != nil {
		return err
	}
	publicKey, err := updatemanifest.LoadPublicKey(*publicPath)
	if err != nil {
		return err
	}
	if err := manifest.Verify(publicKey, now); err != nil {
		return err
	}
	if err := manifest.VerifyArtifact(*artifactPath); err != nil {
		return err
	}
	fmt.Fprintf(
		stdout,
		"verified collector %s for %s with key %s\n",
		manifest.CollectorVersion,
		manifest.Platform,
		manifest.SigningKeyID,
	)
	return nil
}

func writeNewFile(path string, data []byte, mode os.FileMode) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return fmt.Errorf("create %s: %w", path, err)
	}
	if _, err := file.Write(data); err != nil {
		file.Close()
		_ = os.Remove(path)
		return fmt.Errorf("write %s: %w", path, err)
	}
	if err := file.Sync(); err != nil {
		file.Close()
		_ = os.Remove(path)
		return fmt.Errorf("sync %s: %w", path, err)
	}
	if err := file.Close(); err != nil {
		_ = os.Remove(path)
		return fmt.Errorf("close %s: %w", path, err)
	}
	return nil
}

func printUsage(output io.Writer) {
	fmt.Fprintln(output, "usage: update-manifest <keygen|sign|verify> [flags]")
}
