package evidence

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"strconv"
	"strings"
	"time"
)

const manifestPath = "manifest.json"

var archiveTime = time.Unix(0, 0).UTC()

// Build creates a byte-for-byte deterministic evidence bundle.
func Build(metadata Metadata, entries []Entry) (Artifact, error) {
	metadata, err := normalizeMetadata(metadata)
	if err != nil {
		return Artifact{}, err
	}
	entries, err = normalizeEntries(entries)
	if err != nil {
		return Artifact{}, err
	}

	manifest := Manifest{
		SchemaVersion: SchemaVersion,
		BundleID:      metadata.BundleID,
		TenantID:      metadata.TenantID,
		SiteID:        metadata.SiteID,
		CaptureFrom:   metadata.CaptureFrom.Format(time.RFC3339Nano),
		CaptureTo:     metadata.CaptureTo.Format(time.RFC3339Nano),
		GeneratedAt:   metadata.GeneratedAt.Format(time.RFC3339Nano),
		Producer:      metadata.Producer,
		Entries:       make([]ManifestEntry, len(entries)),
	}
	for index, entry := range entries {
		digest := sha256.Sum256(entry.Content)
		manifest.Entries[index] = ManifestEntry{
			Path:      entry.Path,
			MediaType: entry.MediaType,
			Size:      int64(len(entry.Content)),
			SHA256:    hex.EncodeToString(digest[:]),
		}
	}
	manifestBytes, err := json.Marshal(manifest)
	if err != nil {
		return Artifact{}, fmt.Errorf("%w: encode manifest: %v", ErrInvalid, err)
	}

	var output bytes.Buffer
	gzipWriter, err := gzip.NewWriterLevel(&output, gzip.BestCompression)
	if err != nil {
		return Artifact{}, fmt.Errorf("%w: create compressor: %v", ErrInvalid, err)
	}
	gzipWriter.Header.ModTime = archiveTime
	gzipWriter.Header.OS = 255
	tarWriter := tar.NewWriter(gzipWriter)
	if err := writeEntry(tarWriter, manifestPath, manifestBytes); err != nil {
		return Artifact{}, err
	}
	for _, entry := range entries {
		if err := writeEntry(tarWriter, entry.Path, entry.Content); err != nil {
			return Artifact{}, err
		}
	}
	if err := tarWriter.Close(); err != nil {
		return Artifact{}, fmt.Errorf("%w: close archive: %v", ErrInvalid, err)
	}
	if err := gzipWriter.Close(); err != nil {
		return Artifact{}, fmt.Errorf("%w: close compressor: %v", ErrInvalid, err)
	}
	if output.Len() > MaxArchiveBytes {
		return Artifact{}, ErrTooLarge
	}
	bundle := append([]byte(nil), output.Bytes()...)
	digest := sha256.Sum256(bundle)
	return Artifact{
		Bytes:    bundle,
		Size:     int64(len(bundle)),
		SHA256:   hex.EncodeToString(digest[:]),
		Manifest: manifest,
	}, nil
}

// Verify validates canonical structure and every declared entry digest.
func Verify(bundle []byte) (Manifest, error) {
	if len(bundle) == 0 {
		return Manifest{}, ErrInvalid
	}
	if len(bundle) > MaxArchiveBytes {
		return Manifest{}, ErrTooLarge
	}
	source := bytes.NewReader(bundle)
	gzipReader, err := gzip.NewReader(source)
	if err != nil {
		return Manifest{}, integrityError("gzip header", err)
	}
	gzipReader.Multistream(false)
	if (!gzipReader.ModTime.IsZero() && !gzipReader.ModTime.Equal(archiveTime)) ||
		gzipReader.Name != "" || gzipReader.Comment != "" ||
		len(gzipReader.Extra) != 0 || gzipReader.OS != 255 {
		return Manifest{}, invalidError("non-canonical gzip header")
	}
	tarReader := tar.NewReader(gzipReader)
	header, err := tarReader.Next()
	if err != nil {
		return Manifest{}, integrityError("manifest header", err)
	}
	if err := validateHeader(header, manifestPath, header.Size); err != nil {
		return Manifest{}, err
	}
	if header.Size <= 0 || header.Size > maxManifestBytes {
		return Manifest{}, ErrTooLarge
	}
	manifestBytes, err := readExact(tarReader, header.Size)
	if err != nil {
		return Manifest{}, integrityError("manifest body", err)
	}
	manifest, err := decodeManifest(manifestBytes)
	if err != nil {
		return Manifest{}, err
	}

	for _, declared := range manifest.Entries {
		header, err = tarReader.Next()
		if err != nil {
			return Manifest{}, integrityError("missing entry "+declared.Path, err)
		}
		if header.Size != declared.Size {
			return Manifest{}, integrityError("size "+declared.Path, nil)
		}
		if err := validateHeader(header, declared.Path, declared.Size); err != nil {
			return Manifest{}, err
		}
		content, err := readExact(tarReader, declared.Size)
		if err != nil {
			return Manifest{}, integrityError("entry "+declared.Path, err)
		}
		digest := sha256.Sum256(content)
		if hex.EncodeToString(digest[:]) != declared.SHA256 {
			return Manifest{}, integrityError("digest "+declared.Path, nil)
		}
	}
	if extra, nextErr := tarReader.Next(); nextErr != io.EOF {
		if nextErr != nil {
			return Manifest{}, integrityError("archive trailer", nextErr)
		}
		return Manifest{}, invalidError("undeclared entry " + extra.Name)
	}
	if _, err := io.Copy(io.Discard, gzipReader); err != nil {
		return Manifest{}, integrityError("gzip trailer", err)
	}
	if err := gzipReader.Close(); err != nil {
		return Manifest{}, integrityError("close gzip", err)
	}
	if source.Len() != 0 {
		return Manifest{}, invalidError("trailing compressed data")
	}
	return manifest, nil
}

func decodeManifest(data []byte) (Manifest, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var manifest Manifest
	if err := decoder.Decode(&manifest); err != nil {
		return Manifest{}, invalidError("manifest JSON")
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return Manifest{}, invalidError("trailing manifest JSON")
	}
	if manifest.SchemaVersion != SchemaVersion || !validUUID(manifest.BundleID) ||
		!identityPattern.MatchString(manifest.TenantID) ||
		!identityPattern.MatchString(manifest.SiteID) ||
		len(manifest.Producer) > maxProducerBytes ||
		!producerPattern.MatchString(manifest.Producer) ||
		len(manifest.Entries) == 0 || len(manifest.Entries) > MaxEntries {
		return Manifest{}, ErrInvalid
	}
	from, err := parseCanonicalTime(manifest.CaptureFrom)
	if err != nil {
		return Manifest{}, err
	}
	to, err := parseCanonicalTime(manifest.CaptureTo)
	if err != nil {
		return Manifest{}, err
	}
	generated, err := parseCanonicalTime(manifest.GeneratedAt)
	if err != nil {
		return Manifest{}, err
	}
	if _, err := normalizeMetadata(Metadata{
		BundleID: manifest.BundleID, TenantID: manifest.TenantID, SiteID: manifest.SiteID,
		CaptureFrom: from, CaptureTo: to, GeneratedAt: generated, Producer: manifest.Producer,
	}); err != nil {
		return Manifest{}, err
	}

	total := int64(0)
	previous := ""
	for _, entry := range manifest.Entries {
		mediaType, _, parseErr := mime.ParseMediaType(entry.MediaType)
		if !safePath(entry.Path) || entry.Path == manifestPath ||
			entry.Path <= previous || parseErr != nil || mediaType != entry.MediaType ||
			len(entry.MediaType) > maxMediaTypeBytes ||
			entry.Size < 0 || entry.Size > MaxEntryBytes ||
			len(entry.SHA256) != sha256.Size*2 ||
			strings.ToLower(entry.SHA256) != entry.SHA256 {
			return Manifest{}, ErrInvalid
		}
		if _, err := hex.DecodeString(entry.SHA256); err != nil {
			return Manifest{}, ErrInvalid
		}
		total += entry.Size
		if total > MaxTotalBytes {
			return Manifest{}, ErrTooLarge
		}
		previous = entry.Path
	}
	canonical, err := json.Marshal(manifest)
	if err != nil || !bytes.Equal(canonical, data) {
		return Manifest{}, invalidError("non-canonical manifest")
	}
	return manifest, nil
}

func parseCanonicalTime(value string) (time.Time, error) {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil || parsed.Location() != time.UTC ||
		parsed.Format(time.RFC3339Nano) != value {
		return time.Time{}, ErrInvalid
	}
	return parsed, nil
}

func writeEntry(writer *tar.Writer, name string, content []byte) error {
	header := &tar.Header{
		Name: name, Mode: 0o600, Size: int64(len(content)),
		ModTime: archiveTime, Typeflag: tar.TypeReg, Format: tar.FormatUSTAR,
	}
	if err := writer.WriteHeader(header); err != nil {
		return fmt.Errorf("%w: write header: %v", ErrInvalid, err)
	}
	if _, err := writer.Write(content); err != nil {
		return fmt.Errorf("%w: write entry: %v", ErrInvalid, err)
	}
	return nil
}

func validateHeader(header *tar.Header, expected string, size int64) error {
	if header.Name != expected || header.Size != size ||
		header.Typeflag != tar.TypeReg || header.Mode != 0o600 ||
		header.Uid != 0 || header.Gid != 0 ||
		!header.ModTime.Equal(archiveTime) ||
		header.Linkname != "" || header.Uname != "" || header.Gname != "" ||
		len(header.PAXRecords) != 0 || header.Format != tar.FormatUSTAR {
		return invalidError("non-canonical tar header " + strconv.Quote(expected))
	}
	return nil
}

func readExact(reader io.Reader, size int64) ([]byte, error) {
	if size < 0 || size > MaxTotalBytes {
		return nil, ErrTooLarge
	}
	content := make([]byte, size)
	_, err := io.ReadFull(reader, content)
	return content, err
}

func invalidError(detail string) error {
	return fmt.Errorf("%w: %s", ErrInvalid, detail)
}

func integrityError(detail string, cause error) error {
	if cause == nil {
		return fmt.Errorf("%w: %s", ErrIntegrity, detail)
	}
	return fmt.Errorf("%w: %s: %v", ErrIntegrity, detail, cause)
}
