//go:build integration

package maintenance

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestMaintenanceLifecycleAndAuthorization(t *testing.T) {
	databaseURL := os.Getenv("SENTINEL_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("SENTINEL_TEST_DATABASE_URL is not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	seedMaintenanceIntegration(t, ctx, pool)

	store := NewStore(pool, 5*time.Second)
	now := time.Now().UTC().Truncate(time.Second)
	operator := Access{
		UserID:   "operator-1",
		Role:     "operator",
		SiteIDs:  []string{"site-a"},
		IssuedAt: now,
	}
	window, err := store.Create(ctx, operator, CreateInput{
		SiteID:   "site-a",
		StartsAt: now.Add(-time.Minute),
		EndsAt:   now.Add(time.Hour),
		Reason:   "integration work",
	})
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if window.State != "active" || window.Version != 1 {
		t.Fatalf("Create() = %+v", window)
	}
	if _, err := store.Create(ctx, operator, CreateInput{
		SiteID:   "site-a",
		StartsAt: now,
		EndsAt:   now.Add(30 * time.Minute),
		Reason:   "overlap",
	}); !errors.Is(err, ErrConflict) {
		t.Fatalf("overlapping Create() error = %v, want ErrConflict", err)
	}
	listed, err := store.List(ctx, operator, ListFilter{
		SiteID: "site-a",
		State:  "active",
		Limit:  10,
	})
	if err != nil || len(listed) != 1 || listed[0].ID != window.ID {
		t.Fatalf("List() = %+v, %v", listed, err)
	}
	ended, err := store.End(ctx, operator, window.ID, EndInput{ExpectedVersion: 1})
	if err != nil || ended.State != "ended" || ended.Version != 2 {
		t.Fatalf("End() = %+v, %v", ended, err)
	}
	if _, err := store.End(
		ctx, operator, window.ID, EndInput{ExpectedVersion: 1},
	); !errors.Is(err, ErrConflict) {
		t.Fatalf("second End() error = %v, want ErrConflict", err)
	}

	var auditCount int
	if err := pool.QueryRow(ctx, `
		SELECT count(*) FROM operational_audit_log
		WHERE resource_id = $1`, window.ID).Scan(&auditCount); err != nil {
		t.Fatal(err)
	}
	if auditCount != 2 {
		t.Fatalf("audit count = %d, want 2", auditCount)
	}
	if _, err := pool.Exec(ctx, `
		UPDATE operational_audit_log SET details = '{"changed":true}'::jsonb
		WHERE resource_id = $1`, window.ID); err == nil {
		t.Fatal("audit update unexpectedly succeeded")
	}

	unauthorized := operator
	unauthorized.SiteIDs = []string{"site-b"}
	if _, err := store.List(ctx, unauthorized, ListFilter{
		SiteID: "site-a",
		Limit:  10,
	}); err != nil {
		t.Fatalf("unauthorized List() error = %v", err)
	}
	if _, err := store.Create(ctx, unauthorized, CreateInput{
		SiteID:   "site-a",
		StartsAt: now,
		EndsAt:   now.Add(time.Hour),
		Reason:   "hidden",
	}); !errors.Is(err, ErrNotFound) {
		t.Fatalf("unauthorized Create() error = %v", err)
	}
}

func seedMaintenanceIntegration(
	t *testing.T, ctx context.Context, pool *pgxpool.Pool,
) {
	t.Helper()
	if _, err := pool.Exec(ctx, `
		TRUNCATE operational_audit_log, maintenance_windows,
			user_site_access, users, enrollment_tokens, collectors,
			durable_events, federation_outbox, sites CASCADE;
		INSERT INTO sites (site_id, display_name)
		VALUES ('site-a', 'Site A'), ('site-b', 'Site B');
		INSERT INTO users (user_id, role)
		VALUES ('operator-1', 'operator');
		INSERT INTO user_site_access (user_id, site_id)
		VALUES ('operator-1', 'site-a')`); err != nil {
		t.Fatalf("seed database: %v", err)
	}
}
