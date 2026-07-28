// Package evidence creates and verifies deterministic evidence bundles.
package evidence

import (
	"errors"
	"mime"
	"path"
	"regexp"
	"sort"
	"strings"
	"time"
)

const (
	// SchemaVersion is the only evidence manifest version supported here.
	SchemaVersion = 1
	// MaxEntries bounds files in one evidence bundle.
	MaxEntries = 128
	// MaxEntryBytes bounds one evidence entry at 4 MiB.
	MaxEntryBytes = 4 << 20
	// MaxTotalBytes bounds uncompressed evidence content at 32 MiB.
	MaxTotalBytes = 32 << 20
	// MaxArchiveBytes bounds an accepted compressed archive at 40 MiB.
	MaxArchiveBytes = 40 << 20
	// MaxCaptureWindow bounds one bundle's observation interval.
	MaxCaptureWindow = 24 * time.Hour

	maxPathBytes      = 100
	maxMediaTypeBytes = 128
	maxProducerBytes  = 128
	maxManifestBytes  = 1 << 20
)

var (
	identityPattern = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)
	producerPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$`)

	// ErrInvalid indicates a contract or canonical-format violation.
	ErrInvalid = errors.New("invalid evidence bundle")
	// ErrTooLarge indicates a configured evidence size bound was exceeded.
	ErrTooLarge = errors.New("evidence bundle exceeds size bound")
	// ErrIntegrity indicates content did not match its declared manifest.
	ErrIntegrity = errors.New("evidence bundle integrity check failed")
)

// Metadata identifies one site-scoped evidence capture.
type Metadata struct {
	BundleID    string
	TenantID    string
	SiteID      string
	CaptureFrom time.Time
	CaptureTo   time.Time
	GeneratedAt time.Time
	Producer    string
}

// Entry is one caller-allow-listed byte object included in a bundle.
type Entry struct {
	Path      string
	MediaType string
	Content   []byte
}

// Manifest is the canonical first archive entry.
type Manifest struct {
	SchemaVersion int             `json:"schema_version"`
	BundleID      string          `json:"bundle_id"`
	TenantID      string          `json:"tenant_id"`
	SiteID        string          `json:"site_id"`
	CaptureFrom   string          `json:"capture_from"`
	CaptureTo     string          `json:"capture_to"`
	GeneratedAt   string          `json:"generated_at"`
	Producer      string          `json:"producer"`
	Entries       []ManifestEntry `json:"entries"`
}

// ManifestEntry authenticates one archive entry.
type ManifestEntry struct {
	Path      string `json:"path"`
	MediaType string `json:"media_type"`
	Size      int64  `json:"size"`
	SHA256    string `json:"sha256"`
}

// Artifact is a complete compressed bundle plus transport integrity metadata.
type Artifact struct {
	Bytes    []byte
	Size     int64
	SHA256   string
	Manifest Manifest
}

func normalizeMetadata(input Metadata) (Metadata, error) {
	input.BundleID = strings.TrimSpace(input.BundleID)
	input.TenantID = strings.TrimSpace(input.TenantID)
	input.SiteID = strings.TrimSpace(input.SiteID)
	input.Producer = strings.TrimSpace(input.Producer)
	input.CaptureFrom = input.CaptureFrom.UTC()
	input.CaptureTo = input.CaptureTo.UTC()
	input.GeneratedAt = input.GeneratedAt.UTC()
	if !validUUID(input.BundleID) ||
		!identityPattern.MatchString(input.TenantID) ||
		!identityPattern.MatchString(input.SiteID) ||
		len(input.Producer) > maxProducerBytes ||
		!producerPattern.MatchString(input.Producer) ||
		input.CaptureFrom.IsZero() ||
		input.CaptureTo.IsZero() ||
		input.GeneratedAt.IsZero() ||
		!input.CaptureTo.After(input.CaptureFrom) ||
		input.CaptureTo.Sub(input.CaptureFrom) > MaxCaptureWindow ||
		input.GeneratedAt.Before(input.CaptureTo) {
		return Metadata{}, ErrInvalid
	}
	return input, nil
}

func normalizeEntries(input []Entry) ([]Entry, error) {
	if len(input) == 0 || len(input) > MaxEntries {
		return nil, ErrInvalid
	}
	result := make([]Entry, len(input))
	total := 0
	seen := make(map[string]struct{}, len(input))
	for index, entry := range input {
		entry.Path = strings.TrimSpace(entry.Path)
		entry.MediaType = strings.TrimSpace(entry.MediaType)
		if !safePath(entry.Path) || entry.Path == "manifest.json" {
			return nil, ErrInvalid
		}
		if _, duplicate := seen[entry.Path]; duplicate {
			return nil, ErrInvalid
		}
		mediaType, _, err := mime.ParseMediaType(entry.MediaType)
		if err != nil || mediaType != entry.MediaType ||
			len(entry.MediaType) > maxMediaTypeBytes {
			return nil, ErrInvalid
		}
		if len(entry.Content) > MaxEntryBytes {
			return nil, ErrTooLarge
		}
		total += len(entry.Content)
		if total > MaxTotalBytes {
			return nil, ErrTooLarge
		}
		seen[entry.Path] = struct{}{}
		result[index] = Entry{
			Path:      entry.Path,
			MediaType: entry.MediaType,
			Content:   append([]byte(nil), entry.Content...),
		}
	}
	sort.Slice(result, func(left, right int) bool {
		return result[left].Path < result[right].Path
	})
	return result, nil
}

func safePath(value string) bool {
	if value == "" || len(value) > maxPathBytes ||
		strings.Contains(value, "\\") ||
		strings.ContainsRune(value, '\x00') ||
		path.IsAbs(value) ||
		path.Clean(value) != value ||
		value == "." ||
		strings.HasPrefix(value, "../") {
		return false
	}
	for _, part := range strings.Split(value, "/") {
		if part == "" || part == "." || part == ".." {
			return false
		}
	}
	return true
}

func validUUID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for index, character := range value {
		if index == 8 || index == 13 || index == 18 || index == 23 {
			if character != '-' {
				return false
			}
			continue
		}
		if !((character >= '0' && character <= '9') ||
			(character >= 'a' && character <= 'f')) {
			return false
		}
	}
	return true
}
