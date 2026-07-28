//go:build integration

package migrations

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestRunnerAppliesAndRevalidatesMigrations(t *testing.T) {
	databaseURL := os.Getenv("SENTINEL_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("SENTINEL_TEST_DATABASE_URL is not set")
	}

	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("pgxpool.New() error = %v", err)
	}
	defer pool.Close()

	resetDatabase(t, ctx, pool)
	runner := NewRunner(pool)
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("first Run() error = %v", err)
	}
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("idempotent Run() error = %v", err)
	}

	var count int
	if err := pool.QueryRow(ctx, "SELECT count(*) FROM sentinel_schema_migrations").Scan(&count); err != nil {
		t.Fatalf("count migration records: %v", err)
	}
	expected, err := loadMigrations(embeddedFiles)
	if err != nil {
		t.Fatalf("load embedded migrations: %v", err)
	}
	if count != len(expected) {
		t.Fatalf("migration record count = %d, want %d", count, len(expected))
	}

	for _, table := range []string{"maintenance_windows", "operational_audit_log"} {
		var exists bool
		if err := pool.QueryRow(
			ctx,
			"SELECT to_regclass('public.' || $1) IS NOT NULL",
			table,
		).Scan(&exists); err != nil {
			t.Fatalf("check table %s: %v", table, err)
		}
		if !exists {
			t.Fatalf("table %s was not created", table)
		}
	}
}

func TestRunnerRejectsChangedAppliedMigration(t *testing.T) {
	databaseURL := os.Getenv("SENTINEL_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("SENTINEL_TEST_DATABASE_URL is not set")
	}

	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("pgxpool.New() error = %v", err)
	}
	defer pool.Close()

	resetDatabase(t, ctx, pool)
	runner := NewRunner(pool)
	if err := runner.Run(ctx); err != nil {
		t.Fatalf("first Run() error = %v", err)
	}
	if _, err := pool.Exec(ctx, `
UPDATE sentinel_schema_migrations
SET sha256 = decode(repeat('00', 32), 'hex')
WHERE version = 1`); err != nil {
		t.Fatalf("corrupt migration checksum: %v", err)
	}
	if err := runner.Run(ctx); !errors.Is(err, ErrMigrationChanged) {
		t.Fatalf("Run() error = %v, want ErrMigrationChanged", err)
	}
}

func resetDatabase(t *testing.T, ctx context.Context, pool *pgxpool.Pool) {
	t.Helper()
	const reset = `
DROP TABLE IF EXISTS operational_audit_log, maintenance_windows,
    user_site_access, users, federation_outbox, durable_events,
    enrollment_tokens, collectors, sites, sentinel_schema_migrations CASCADE;
DROP FUNCTION IF EXISTS reject_operational_audit_mutation()`
	if _, err := pool.Exec(ctx, reset); err != nil {
		t.Fatalf("reset database: %v", err)
	}
}
