//go:build integration

package registry

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestListCollectorsEnforcesCurrentUserAndTokenSiteScope(t *testing.T) {
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

	const (
		siteID      = "api-test-site"
		collectorID = "api-test-node"
		userID      = "api-test-viewer"
	)
	cleanup := func() {
		_, _ = pool.Exec(ctx, "DELETE FROM users WHERE user_id = $1", userID)
		_, _ = pool.Exec(
			ctx,
			"DELETE FROM collectors WHERE site_id = $1 AND collector_id = $2",
			siteID,
			collectorID,
		)
		_, _ = pool.Exec(ctx, "DELETE FROM sites WHERE site_id = $1", siteID)
	}
	cleanup()
	defer cleanup()

	if _, err := pool.Exec(ctx, `
		INSERT INTO sites (site_id, display_name) VALUES ($1, 'API integration')
		`, siteID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, `
		INSERT INTO collectors (site_id, collector_id, last_seen)
		VALUES ($1, $2, now())
		`, siteID, collectorID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(
		ctx,
		"INSERT INTO users (user_id, role) VALUES ($1, 'viewer')",
		userID,
	); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(
		ctx,
		"INSERT INTO user_site_access (user_id, site_id) VALUES ($1, $2)",
		userID,
		siteID,
	); err != nil {
		t.Fatal(err)
	}

	store := NewStore(pool, 3*time.Second)
	issuedAt := time.Now()
	collectors, err := store.ListCollectors(ctx, Access{
		UserID: userID, Role: "viewer", SiteIDs: []string{siteID}, IssuedAt: issuedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 1 || collectors[0].CollectorID != collectorID ||
		collectors[0].LastSeen == nil {
		t.Fatalf("unexpected collectors: %+v", collectors)
	}

	collectors, err = store.ListCollectors(ctx, Access{
		UserID: userID, Role: "viewer", SiteIDs: []string{"other-site"}, IssuedAt: issuedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 0 {
		t.Fatalf("unauthorized site leaked collectors: %+v", collectors)
	}
	authorized, err := store.AuthorizeSite(ctx, Access{
		UserID: userID, Role: "viewer", SiteIDs: []string{siteID}, IssuedAt: issuedAt,
	}, siteID)
	if err != nil || !authorized {
		t.Fatalf("AuthorizeSite() = %v, %v; want true, nil", authorized, err)
	}
	authorized, err = store.AuthorizeSite(ctx, Access{
		UserID: userID, Role: "viewer", SiteIDs: []string{"other-site"}, IssuedAt: issuedAt,
	}, siteID)
	if err != nil || authorized {
		t.Fatalf("AuthorizeSite() = %v, %v; want false, nil", authorized, err)
	}

	if _, err := pool.Exec(
		ctx,
		"UPDATE users SET token_not_before = now() + interval '1 minute' WHERE user_id = $1",
		userID,
	); err != nil {
		t.Fatal(err)
	}
	collectors, err = store.ListCollectors(ctx, Access{
		UserID: userID, Role: "viewer", SiteIDs: []string{siteID}, IssuedAt: issuedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 0 {
		t.Fatalf("revoked token retained access: %+v", collectors)
	}
	authorized, err = store.AuthorizeSite(ctx, Access{
		UserID: userID, Role: "viewer", SiteIDs: []string{siteID}, IssuedAt: issuedAt,
	}, siteID)
	if err != nil || authorized {
		t.Fatalf("revoked AuthorizeSite() = %v, %v; want false, nil", authorized, err)
	}
}
