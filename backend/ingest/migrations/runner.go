// Package migrations applies the ingest database schema.
package migrations

import (
	"context"
	"crypto/sha256"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"path"
	"regexp"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const advisoryLockID int64 = 0x53454e54494e454c // "SENTINEL"

var (
	//go:embed *.sql
	embeddedFiles embed.FS

	filePattern = regexp.MustCompile(`^([0-9]{6})_([a-z0-9_]+)\.sql$`)

	// ErrDatabaseAhead means the database contains a migration unknown to this
	// binary, so running an older release would be unsafe.
	ErrDatabaseAhead = errors.New("database schema is ahead of this binary")
	// ErrMigrationChanged means an applied migration no longer matches its
	// immutable source file.
	ErrMigrationChanged = errors.New("applied migration has changed")
	// ErrMigrationGap means the applied migrations are not a contiguous prefix.
	ErrMigrationGap = errors.New("database migration history contains a gap")
)

type migration struct {
	version  int64
	filename string
	checksum [sha256.Size]byte
	sql      string
}

type appliedMigration struct {
	filename string
	checksum []byte
}

// Runner serializes and transactionally applies all embedded SQL migrations.
type Runner struct {
	pool *pgxpool.Pool
}

// NewRunner returns a migration runner backed by pool.
func NewRunner(pool *pgxpool.Pool) *Runner {
	return &Runner{pool: pool}
}

// Run validates immutable migration history and applies pending migrations.
func (r *Runner) Run(ctx context.Context) error {
	if r.pool == nil {
		return errors.New("migration pool is nil")
	}

	migrations, err := loadMigrations(embeddedFiles)
	if err != nil {
		return err
	}

	conn, err := r.pool.Acquire(ctx)
	if err != nil {
		return fmt.Errorf("acquire migration connection: %w", err)
	}
	defer conn.Release()

	if _, err := conn.Exec(ctx, "SELECT pg_advisory_lock($1)", advisoryLockID); err != nil {
		return fmt.Errorf("acquire migration advisory lock: %w", err)
	}
	defer unlock(conn)

	if err := ensureMetadataTable(ctx, conn.Conn()); err != nil {
		return err
	}

	applied, err := readApplied(ctx, conn.Conn())
	if err != nil {
		return err
	}
	if err := validateHistory(migrations, applied); err != nil {
		return err
	}

	for _, item := range migrations {
		if _, ok := applied[item.version]; ok {
			continue
		}
		if err := applyOne(ctx, conn.Conn(), item); err != nil {
			return err
		}
	}
	return nil
}

func loadMigrations(source fs.FS) ([]migration, error) {
	entries, err := fs.ReadDir(source, ".")
	if err != nil {
		return nil, fmt.Errorf("read embedded migrations: %w", err)
	}

	var result []migration
	seen := make(map[int64]string)
	for _, entry := range entries {
		if entry.IsDir() || path.Ext(entry.Name()) != ".sql" {
			continue
		}
		match := filePattern.FindStringSubmatch(entry.Name())
		if match == nil {
			return nil, fmt.Errorf("invalid migration filename %q", entry.Name())
		}
		version, err := strconv.ParseInt(match[1], 10, 64)
		if err != nil || version == 0 {
			return nil, fmt.Errorf("invalid migration version in %q", entry.Name())
		}
		if previous, ok := seen[version]; ok {
			return nil, fmt.Errorf("duplicate migration version %06d in %q and %q", version, previous, entry.Name())
		}
		contents, err := fs.ReadFile(source, entry.Name())
		if err != nil {
			return nil, fmt.Errorf("read migration %q: %w", entry.Name(), err)
		}
		seen[version] = entry.Name()
		result = append(result, migration{
			version:  version,
			filename: entry.Name(),
			checksum: sha256.Sum256(contents),
			sql:      string(contents),
		})
	}
	if len(result) == 0 {
		return nil, errors.New("no embedded migrations found")
	}
	sort.Slice(result, func(i, j int) bool {
		return result[i].version < result[j].version
	})
	return result, nil
}

func ensureMetadataTable(ctx context.Context, conn *pgx.Conn) error {
	const statement = `
CREATE TABLE IF NOT EXISTS sentinel_schema_migrations (
    version BIGINT PRIMARY KEY CHECK (version > 0),
    filename TEXT NOT NULL UNIQUE,
    sha256 BYTEA NOT NULL CHECK (octet_length(sha256) = 32),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)`
	if _, err := conn.Exec(ctx, statement); err != nil {
		return fmt.Errorf("create migration metadata table: %w", err)
	}
	return nil
}

func readApplied(ctx context.Context, conn *pgx.Conn) (map[int64]appliedMigration, error) {
	rows, err := conn.Query(ctx, `
SELECT version, filename, sha256
FROM sentinel_schema_migrations
ORDER BY version`)
	if err != nil {
		return nil, fmt.Errorf("read migration history: %w", err)
	}
	defer rows.Close()

	result := make(map[int64]appliedMigration)
	for rows.Next() {
		var version int64
		var item appliedMigration
		if err := rows.Scan(&version, &item.filename, &item.checksum); err != nil {
			return nil, fmt.Errorf("scan migration history: %w", err)
		}
		result[version] = item
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate migration history: %w", err)
	}
	return result, nil
}

func validateHistory(known []migration, applied map[int64]appliedMigration) error {
	knownByVersion := make(map[int64]migration, len(known))
	for _, item := range known {
		knownByVersion[item.version] = item
	}
	for version, recorded := range applied {
		item, ok := knownByVersion[version]
		if !ok {
			return fmt.Errorf("%w: unknown version %06d", ErrDatabaseAhead, version)
		}
		if recorded.filename != item.filename ||
			!equalChecksum(recorded.checksum, item.checksum[:]) {
			return fmt.Errorf("%w: version %06d (%s)", ErrMigrationChanged, version, recorded.filename)
		}
	}

	missingSeen := false
	for _, item := range known {
		_, ok := applied[item.version]
		if !ok {
			missingSeen = true
			continue
		}
		if missingSeen {
			return fmt.Errorf("%w before version %06d", ErrMigrationGap, item.version)
		}
	}
	return nil
}

func equalChecksum(left, right []byte) bool {
	if len(left) != len(right) {
		return false
	}
	var different byte
	for i := range left {
		different |= left[i] ^ right[i]
	}
	return different == 0
}

func applyOne(ctx context.Context, conn *pgx.Conn, item migration) error {
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return fmt.Errorf("begin migration %06d: %w", item.version, err)
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()

	if _, err := tx.Exec(ctx, item.sql); err != nil {
		return fmt.Errorf("execute migration %06d (%s): %w", item.version, item.filename, err)
	}
	if _, err := tx.Exec(ctx, `
INSERT INTO sentinel_schema_migrations (version, filename, sha256)
VALUES ($1, $2, $3)`, item.version, item.filename, item.checksum[:]); err != nil {
		return fmt.Errorf("record migration %06d: %w", item.version, err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit migration %06d: %w", item.version, err)
	}
	return nil
}

func unlock(conn *pgxpool.Conn) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, _ = conn.Exec(ctx, "SELECT pg_advisory_unlock($1)", advisoryLockID)
}
