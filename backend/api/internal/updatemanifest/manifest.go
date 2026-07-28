// Package updatemanifest defines the release-side SENTINEL collector update
// manifest contract. The node-side updater consumes the same canonical bytes.
package updatemanifest

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	SchemaVersion   = 1
	MaxArtifactSize = int64(256 * 1024 * 1024)
	MaxValidity     = 31 * 24 * time.Hour
)

var (
	versionPattern = regexp.MustCompile(`^2\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)
	digestPattern  = regexp.MustCompile(`^[0-9a-f]{64}$`)
	keyIDPattern   = regexp.MustCompile(`^[0-9a-f]{16}$`)
)

// Manifest is schema v1. Times use exact UTC RFC3339 seconds
// (YYYY-MM-DDTHH:MM:SSZ); accepting alternate encodings would make
// cross-language canonicalization ambiguous.
type Manifest struct {
	SchemaVersion           int    `json:"schema_version"`
	CollectorVersion        string `json:"collector_version"`
	Platform                string `json:"platform"`
	SHA256                  string `json:"sha256"`
	SizeBytes               int64  `json:"size_bytes"`
	NotBefore               string `json:"not_before"`
	ExpiresAt               string `json:"expires_at"`
	MinSupportedFromVersion string `json:"min_supported_from_version"`
	Rollback                bool   `json:"rollback"`
	SigningKeyID            string `json:"signing_key_id"`
	Signature               string `json:"signature"`
}

// CanonicalPayload returns compact JSON with lexicographically sorted keys and
// no signature field. This exact byte sequence is signed and is deliberately
// simple to reproduce with Python's json.dumps(sort_keys=True,separators=(",",":")).
func (m Manifest) CanonicalPayload() ([]byte, error) {
	if err := m.validate(false); err != nil {
		return nil, err
	}
	return json.Marshal(map[string]any{
		"collector_version":          m.CollectorVersion,
		"expires_at":                 m.ExpiresAt,
		"min_supported_from_version": m.MinSupportedFromVersion,
		"not_before":                 m.NotBefore,
		"platform":                   m.Platform,
		"rollback":                   m.Rollback,
		"schema_version":             m.SchemaVersion,
		"sha256":                     m.SHA256,
		"signing_key_id":             m.SigningKeyID,
		"size_bytes":                 m.SizeBytes,
	})
}

// MarshalCanonical returns the only accepted on-disk JSON representation.
func (m Manifest) MarshalCanonical() ([]byte, error) {
	if err := m.validate(true); err != nil {
		return nil, err
	}
	return json.Marshal(map[string]any{
		"collector_version":          m.CollectorVersion,
		"expires_at":                 m.ExpiresAt,
		"min_supported_from_version": m.MinSupportedFromVersion,
		"not_before":                 m.NotBefore,
		"platform":                   m.Platform,
		"rollback":                   m.Rollback,
		"schema_version":             m.SchemaVersion,
		"sha256":                     m.SHA256,
		"signature":                  m.Signature,
		"signing_key_id":             m.SigningKeyID,
		"size_bytes":                 m.SizeBytes,
	})
}

// ParseCanonical rejects unknown fields, trailing JSON, duplicate/reordered
// keys, and alternate whitespace by requiring the canonical re-encoding to
// equal the input after trimming only outer whitespace.
func ParseCanonical(data []byte) (Manifest, error) {
	var manifest Manifest
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&manifest); err != nil {
		return Manifest{}, fmt.Errorf("decode manifest: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return Manifest{}, errors.New("decode manifest: trailing JSON value")
		}
		return Manifest{}, fmt.Errorf("decode manifest trailing data: %w", err)
	}
	if err := manifest.validate(true); err != nil {
		return Manifest{}, err
	}
	canonical, err := manifest.MarshalCanonical()
	if err != nil {
		return Manifest{}, err
	}
	if !bytes.Equal(bytes.TrimSpace(data), canonical) {
		return Manifest{}, errors.New("manifest is not canonical JSON")
	}
	return manifest, nil
}

// Sign fills SigningKeyID and Signature after validating every unsigned field.
func (m *Manifest) Sign(privateKey ed25519.PrivateKey) error {
	if len(privateKey) != ed25519.PrivateKeySize {
		return fmt.Errorf("private key must be %d bytes", ed25519.PrivateKeySize)
	}
	publicKey, ok := privateKey.Public().(ed25519.PublicKey)
	if !ok {
		return errors.New("private key did not yield an Ed25519 public key")
	}
	m.SigningKeyID = KeyID(publicKey)
	m.Signature = ""
	payload, err := m.CanonicalPayload()
	if err != nil {
		return err
	}
	m.Signature = base64.StdEncoding.EncodeToString(ed25519.Sign(privateKey, payload))
	return m.validate(true)
}

// Verify authenticates the canonical payload and enforces its validity window.
func (m Manifest) Verify(publicKey ed25519.PublicKey, now time.Time) error {
	if err := m.validate(true); err != nil {
		return err
	}
	if len(publicKey) != ed25519.PublicKeySize {
		return fmt.Errorf("public key must be %d bytes", ed25519.PublicKeySize)
	}
	if got := KeyID(publicKey); got != m.SigningKeyID {
		return fmt.Errorf("signing_key_id mismatch: manifest %q, key %q", m.SigningKeyID, got)
	}
	notBefore, _ := parseContractTime(m.NotBefore)
	expiresAt, _ := parseContractTime(m.ExpiresAt)
	now = now.UTC()
	if now.Before(notBefore) {
		return fmt.Errorf("manifest is not valid before %s", m.NotBefore)
	}
	if !now.Before(expiresAt) {
		return fmt.Errorf("manifest expired at %s", m.ExpiresAt)
	}
	signature, _ := base64.StdEncoding.DecodeString(m.Signature)
	payload, err := m.CanonicalPayload()
	if err != nil {
		return err
	}
	if !ed25519.Verify(publicKey, payload, signature) {
		return errors.New("invalid Ed25519 manifest signature")
	}
	return nil
}

// KeyID is the first eight bytes of SHA-256(public key), encoded as sixteen
// lowercase hexadecimal characters.
func KeyID(publicKey ed25519.PublicKey) string {
	digest := sha256.Sum256(publicKey)
	return hex.EncodeToString(digest[:8])
}

func (m Manifest) validate(requireSignature bool) error {
	if m.SchemaVersion != SchemaVersion {
		return fmt.Errorf("schema_version must be %d", SchemaVersion)
	}
	if _, err := parseVersion(m.CollectorVersion); err != nil {
		return fmt.Errorf("collector_version: %w", err)
	}
	if _, err := parseVersion(m.MinSupportedFromVersion); err != nil {
		return fmt.Errorf("min_supported_from_version: %w", err)
	}
	if compareVersions(m.MinSupportedFromVersion, m.CollectorVersion) > 0 {
		return errors.New("min_supported_from_version must not exceed collector_version")
	}
	if m.Platform != "linux/amd64" && m.Platform != "linux/arm64" {
		return fmt.Errorf("unsupported platform %q", m.Platform)
	}
	if !digestPattern.MatchString(m.SHA256) {
		return errors.New("sha256 must be 64 lowercase hexadecimal characters")
	}
	if m.SizeBytes <= 0 || m.SizeBytes > MaxArtifactSize {
		return fmt.Errorf("size_bytes must be between 1 and %d", MaxArtifactSize)
	}
	notBefore, err := parseContractTime(m.NotBefore)
	if err != nil {
		return fmt.Errorf("not_before: %w", err)
	}
	expiresAt, err := parseContractTime(m.ExpiresAt)
	if err != nil {
		return fmt.Errorf("expires_at: %w", err)
	}
	if !expiresAt.After(notBefore) {
		return errors.New("expires_at must be after not_before")
	}
	if expiresAt.Sub(notBefore) > MaxValidity {
		return fmt.Errorf("manifest validity must not exceed %s", MaxValidity)
	}
	if !keyIDPattern.MatchString(m.SigningKeyID) {
		return errors.New("signing_key_id must be 16 lowercase hexadecimal characters")
	}
	if requireSignature {
		signature, err := base64.StdEncoding.DecodeString(m.Signature)
		if err != nil || len(signature) != ed25519.SignatureSize {
			return fmt.Errorf("signature must be padded base64 encoding of %d bytes", ed25519.SignatureSize)
		}
	}
	return nil
}

func parseContractTime(value string) (time.Time, error) {
	parsed, err := time.Parse("2006-01-02T15:04:05Z", value)
	if err != nil || parsed.Format("2006-01-02T15:04:05Z") != value {
		return time.Time{}, errors.New("must use exact UTC RFC3339 seconds (YYYY-MM-DDTHH:MM:SSZ)")
	}
	return parsed, nil
}

func parseVersion(value string) ([3]uint64, error) {
	if !versionPattern.MatchString(value) {
		return [3]uint64{}, errors.New("must be a stable SENTINEL v2 version such as 2.3.1")
	}
	parts := strings.Split(value, ".")
	var parsed [3]uint64
	for index, part := range parts {
		number, err := strconv.ParseUint(part, 10, 64)
		if err != nil {
			return [3]uint64{}, errors.New("contains an invalid numeric component")
		}
		parsed[index] = number
	}
	return parsed, nil
}

func compareVersions(left, right string) int {
	leftParts, _ := parseVersion(left)
	rightParts, _ := parseVersion(right)
	for index := range leftParts {
		if leftParts[index] < rightParts[index] {
			return -1
		}
		if leftParts[index] > rightParts[index] {
			return 1
		}
	}
	return 0
}
