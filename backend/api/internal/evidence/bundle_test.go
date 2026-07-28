package evidence

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"
	"time"
)

func TestBuildIsDeterministicAndVerifiable(t *testing.T) {
	metadata := validMetadata()
	first, err := Build(metadata, []Entry{
		{Path: "metrics/snapshot.json", MediaType: "application/json", Content: []byte(`{"up":true}`)},
		{Path: "logs/probe.txt", MediaType: "text/plain", Content: []byte("healthy\n")},
	})
	if err != nil {
		t.Fatal(err)
	}
	second, err := Build(metadata, []Entry{
		{Path: "logs/probe.txt", MediaType: "text/plain", Content: []byte("healthy\n")},
		{Path: "metrics/snapshot.json", MediaType: "application/json", Content: []byte(`{"up":true}`)},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes, second.Bytes) {
		t.Fatal("same validated content produced different bytes")
	}
	digest := sha256.Sum256(first.Bytes)
	if first.Size != int64(len(first.Bytes)) || first.SHA256 != hex.EncodeToString(digest[:]) {
		t.Fatal("artifact transport metadata is incorrect")
	}
	verified, err := Verify(first.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	if len(verified.Entries) != 2 ||
		verified.Entries[0].Path != "logs/probe.txt" ||
		verified.Entries[1].Path != "metrics/snapshot.json" {
		t.Fatalf("entries are not canonical: %#v", verified.Entries)
	}
}

func TestBuildRejectsInvalidInputs(t *testing.T) {
	tests := []struct {
		name     string
		metadata Metadata
		entries  []Entry
		target   error
	}{
		{name: "metadata", metadata: Metadata{}, entries: validEntries(), target: ErrInvalid},
		{name: "empty", metadata: validMetadata(), target: ErrInvalid},
		{name: "absolute path", metadata: validMetadata(), entries: []Entry{{Path: "/secret", MediaType: "text/plain"}}, target: ErrInvalid},
		{name: "traversal", metadata: validMetadata(), entries: []Entry{{Path: "../secret", MediaType: "text/plain"}}, target: ErrInvalid},
		{name: "reserved", metadata: validMetadata(), entries: []Entry{{Path: manifestPath, MediaType: "application/json"}}, target: ErrInvalid},
		{name: "duplicate", metadata: validMetadata(), entries: []Entry{{Path: "a", MediaType: "text/plain"}, {Path: "a", MediaType: "text/plain"}}, target: ErrInvalid},
		{name: "noncanonical media type", metadata: validMetadata(), entries: []Entry{{Path: "a", MediaType: "text/plain; charset=utf-8"}}, target: ErrInvalid},
		{name: "entry too large", metadata: validMetadata(), entries: []Entry{{Path: "a", MediaType: "application/octet-stream", Content: make([]byte, MaxEntryBytes+1)}}, target: ErrTooLarge},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := Build(test.metadata, test.entries)
			if !errors.Is(err, test.target) {
				t.Fatalf("got %v, want %v", err, test.target)
			}
		})
	}
}

func TestVerifyFailsClosed(t *testing.T) {
	artifact, err := Build(validMetadata(), validEntries())
	if err != nil {
		t.Fatal(err)
	}
	files := unpack(t, artifact.Bytes)

	t.Run("digest mismatch", func(t *testing.T) {
		changed := cloneFiles(files)
		changed[1].body = []byte("tampered")
		_, err := Verify(pack(t, changed))
		if !errors.Is(err, ErrIntegrity) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("undeclared entry", func(t *testing.T) {
		changed := append(cloneFiles(files), testFile{name: "unknown.txt", body: []byte("x")})
		_, err := Verify(pack(t, changed))
		if !errors.Is(err, ErrInvalid) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("duplicate entry", func(t *testing.T) {
		changed := append(cloneFiles(files), files[1])
		_, err := Verify(pack(t, changed))
		if !errors.Is(err, ErrInvalid) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("reordered entry", func(t *testing.T) {
		multiple, buildErr := Build(validMetadata(), []Entry{
			{Path: "a.txt", MediaType: "text/plain", Content: []byte("a")},
			{Path: "b.txt", MediaType: "text/plain", Content: []byte("b")},
		})
		if buildErr != nil {
			t.Fatal(buildErr)
		}
		changed := unpack(t, multiple.Bytes)
		changed[1], changed[2] = changed[2], changed[1]
		_, err := Verify(pack(t, changed))
		if !errors.Is(err, ErrInvalid) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("noncanonical manifest", func(t *testing.T) {
		changed := cloneFiles(files)
		changed[0].body = append(changed[0].body, '\n')
		_, err := Verify(pack(t, changed))
		if !errors.Is(err, ErrInvalid) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("unknown manifest field", func(t *testing.T) {
		changed := cloneFiles(files)
		var raw map[string]any
		if err := json.Unmarshal(changed[0].body, &raw); err != nil {
			t.Fatal(err)
		}
		raw["secret"] = "must not be accepted"
		changed[0].body, _ = json.Marshal(raw)
		_, err := Verify(pack(t, changed))
		if !errors.Is(err, ErrInvalid) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("trailing compressed data", func(t *testing.T) {
		_, err := Verify(append(append([]byte(nil), artifact.Bytes...), 0))
		if !errors.Is(err, ErrInvalid) {
			t.Fatalf("got %v", err)
		}
	})
	t.Run("corrupt archive", func(t *testing.T) {
		changed := append([]byte(nil), artifact.Bytes...)
		changed[len(changed)/2] ^= 0xff
		_, err := Verify(changed)
		if !errors.Is(err, ErrIntegrity) && !errors.Is(err, ErrInvalid) {
			t.Fatalf("got %v", err)
		}
	})
}

func TestManifestTimestampAndCaptureBounds(t *testing.T) {
	metadata := validMetadata()
	metadata.CaptureTo = metadata.CaptureFrom.Add(MaxCaptureWindow + time.Nanosecond)
	if _, err := Build(metadata, validEntries()); !errors.Is(err, ErrInvalid) {
		t.Fatalf("got %v", err)
	}
	metadata = validMetadata()
	metadata.GeneratedAt = metadata.CaptureTo.Add(-time.Second)
	if _, err := Build(metadata, validEntries()); !errors.Is(err, ErrInvalid) {
		t.Fatalf("got %v", err)
	}
}

func validMetadata() Metadata {
	return Metadata{
		BundleID:    "123e4567-e89b-12d3-a456-426614174000",
		TenantID:    "tenant-1",
		SiteID:      "site-1",
		CaptureFrom: time.Date(2026, 7, 28, 12, 0, 0, 123, time.UTC),
		CaptureTo:   time.Date(2026, 7, 28, 12, 5, 0, 456, time.UTC),
		GeneratedAt: time.Date(2026, 7, 28, 12, 5, 1, 789, time.UTC),
		Producer:    "api/1.0.0",
	}
}

func validEntries() []Entry {
	return []Entry{{Path: "status.txt", MediaType: "text/plain", Content: []byte("ok\n")}}
}

type testFile struct {
	name string
	body []byte
}

func unpack(t *testing.T, bundle []byte) []testFile {
	t.Helper()
	gz, err := gzip.NewReader(bytes.NewReader(bundle))
	if err != nil {
		t.Fatal(err)
	}
	reader := tar.NewReader(gz)
	var files []testFile
	for {
		header, err := reader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(reader)
		if err != nil {
			t.Fatal(err)
		}
		files = append(files, testFile{name: header.Name, body: body})
	}
	return files
}

func pack(t *testing.T, files []testFile) []byte {
	t.Helper()
	var output bytes.Buffer
	gz, _ := gzip.NewWriterLevel(&output, gzip.BestCompression)
	gz.Header.ModTime = archiveTime
	gz.Header.OS = 255
	writer := tar.NewWriter(gz)
	for _, file := range files {
		if err := writeEntry(writer, file.name, file.body); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return output.Bytes()
}

func cloneFiles(input []testFile) []testFile {
	output := make([]testFile, len(input))
	for index, file := range input {
		output[index] = testFile{name: file.name, body: append([]byte(nil), file.body...)}
	}
	return output
}

func TestSafePath(t *testing.T) {
	for _, value := range []string{"a", "a/b.json", strings.Repeat("a", maxPathBytes)} {
		if !safePath(value) {
			t.Fatalf("expected safe path %q", value)
		}
	}
	for _, value := range []string{"", ".", "..", "a//b", "a/../b", `a\b`, strings.Repeat("a", maxPathBytes+1)} {
		if safePath(value) {
			t.Fatalf("expected unsafe path %q", value)
		}
	}
}
