package updatemanifest

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
)

// ArtifactMetadata computes the signed size and digest fields without loading
// an entire collector binary into memory.
func ArtifactMetadata(path string) (int64, string, error) {
	file, err := os.Open(path)
	if err != nil {
		return 0, "", fmt.Errorf("open artifact: %w", err)
	}
	defer file.Close()

	hash := sha256.New()
	size, err := io.Copy(hash, io.LimitReader(file, MaxArtifactSize+1))
	if err != nil {
		return 0, "", fmt.Errorf("hash artifact: %w", err)
	}
	if size <= 0 || size > MaxArtifactSize {
		return 0, "", fmt.Errorf("artifact size must be between 1 and %d bytes", MaxArtifactSize)
	}
	return size, hex.EncodeToString(hash.Sum(nil)), nil
}

// VerifyArtifact checks the artifact only after a caller has authenticated the
// manifest signature and validity window.
func (m Manifest) VerifyArtifact(path string) error {
	size, digest, err := ArtifactMetadata(path)
	if err != nil {
		return err
	}
	if size != m.SizeBytes {
		return fmt.Errorf("artifact size mismatch: manifest %d, file %d", m.SizeBytes, size)
	}
	if digest != m.SHA256 {
		return fmt.Errorf("artifact SHA-256 mismatch: manifest %s, file %s", m.SHA256, digest)
	}
	return nil
}
