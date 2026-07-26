package migrations

import (
	"crypto/sha256"
	"errors"
	"testing"
	"testing/fstest"
)

func TestLoadMigrationsSortsAndHashes(t *testing.T) {
	source := fstest.MapFS{
		"000002_second.sql": {Data: []byte("SELECT 2;")},
		"000001_first.sql":  {Data: []byte("SELECT 1;")},
	}

	items, err := loadMigrations(source)
	if err != nil {
		t.Fatalf("loadMigrations() error = %v", err)
	}
	if len(items) != 2 || items[0].version != 1 || items[1].version != 2 {
		t.Fatalf("loadMigrations() returned unexpected order: %#v", items)
	}
	want := sha256.Sum256([]byte("SELECT 1;"))
	if items[0].checksum != want {
		t.Fatalf("checksum = %x, want %x", items[0].checksum, want)
	}
}

func TestLoadMigrationsRejectsInvalidAndDuplicateNames(t *testing.T) {
	tests := map[string]fstest.MapFS{
		"invalid": {
			"1_bad.sql": {Data: []byte("SELECT 1;")},
		},
		"duplicate": {
			"000001_first.sql":  {Data: []byte("SELECT 1;")},
			"000001_second.sql": {Data: []byte("SELECT 2;")},
		},
	}
	for name, source := range tests {
		t.Run(name, func(t *testing.T) {
			if _, err := loadMigrations(source); err == nil {
				t.Fatal("loadMigrations() error = nil, want error")
			}
		})
	}
}

func TestValidateHistory(t *testing.T) {
	firstHash := sha256.Sum256([]byte("one"))
	secondHash := sha256.Sum256([]byte("two"))
	known := []migration{
		{version: 1, filename: "000001_first.sql", checksum: firstHash},
		{version: 2, filename: "000002_second.sql", checksum: secondHash},
	}

	tests := []struct {
		name    string
		applied map[int64]appliedMigration
		wantErr error
	}{
		{name: "empty", applied: map[int64]appliedMigration{}},
		{
			name: "valid prefix",
			applied: map[int64]appliedMigration{
				1: {filename: known[0].filename, checksum: firstHash[:]},
			},
		},
		{
			name: "checksum changed",
			applied: map[int64]appliedMigration{
				1: {filename: known[0].filename, checksum: make([]byte, sha256.Size)},
			},
			wantErr: ErrMigrationChanged,
		},
		{
			name: "database ahead",
			applied: map[int64]appliedMigration{
				3: {filename: "000003_future.sql", checksum: make([]byte, sha256.Size)},
			},
			wantErr: ErrDatabaseAhead,
		},
		{
			name: "gap",
			applied: map[int64]appliedMigration{
				2: {filename: known[1].filename, checksum: secondHash[:]},
			},
			wantErr: ErrMigrationGap,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			err := validateHistory(known, test.applied)
			if !errors.Is(err, test.wantErr) {
				t.Fatalf("validateHistory() error = %v, want %v", err, test.wantErr)
			}
		})
	}
}
