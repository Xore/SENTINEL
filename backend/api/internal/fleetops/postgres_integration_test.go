//go:build integration

package fleetops

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	itSiteA = "fleetops-it-site-a"
	itSiteB = "fleetops-it-site-b"
	itSiteC = "fleetops-it-site-c"
	itUser  = "fleetops-it-viewer"
)

func TestSummaryAndListCollectorsEnforceScopeAndBounds(t *testing.T) {
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

	cleanup := func() {
		_, _ = pool.Exec(ctx, "DELETE FROM users WHERE user_id = $1", itUser)
		for _, siteID := range []string{itSiteA, itSiteB, itSiteC} {
			_, _ = pool.Exec(ctx, "DELETE FROM collectors WHERE site_id = $1", siteID)
			_, _ = pool.Exec(ctx, "DELETE FROM sites WHERE site_id = $1", siteID)
		}
	}
	cleanup()
	defer cleanup()

	for _, siteID := range []string{itSiteA, itSiteB, itSiteC} {
		if _, err := pool.Exec(ctx,
			"INSERT INTO sites (site_id, display_name) VALUES ($1, 'fleetops integration')",
			siteID); err != nil {
			t.Fatal(err)
		}
	}
	// Site A: one collector per lifecycle state; the stale and never_seen
	// collectors also have certificates expiring inside the window.
	fixtures := []string{
		`INSERT INTO collectors (site_id, collector_id, last_seen, certificate_not_after)
		 VALUES ($1, 'alpha', now(), now() + interval '30 days')`,
		`INSERT INTO collectors (site_id, collector_id, last_seen, certificate_not_after)
		 VALUES ($1, 'beta', now() - interval '10 minutes', now() + interval '5 days')`,
		`INSERT INTO collectors (site_id, collector_id, last_seen, disabled_at, certificate_not_after)
		 VALUES ($1, 'gamma', now(), now(), now() + interval '5 days')`,
		`INSERT INTO collectors (site_id, collector_id, certificate_not_after)
		 VALUES ($1, 'delta', now() + interval '2 days')`,
	}
	for _, stmt := range fixtures {
		if _, err := pool.Exec(ctx, stmt, itSiteA); err != nil {
			t.Fatal(err)
		}
	}
	// Site B: one active collector with an expiring certificate.
	if _, err := pool.Exec(ctx, `
		INSERT INTO collectors (site_id, collector_id, last_seen, certificate_not_after)
		VALUES ($1, 'epsilon', now(), now() + interval '10 days')`, itSiteB); err != nil {
		t.Fatal(err)
	}
	// Site C: active collector the user must never observe.
	if _, err := pool.Exec(ctx, `
		INSERT INTO collectors (site_id, collector_id, last_seen)
		VALUES ($1, 'zeta', now())`, itSiteC); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx,
		"INSERT INTO users (user_id, role) VALUES ($1, 'viewer')", itUser); err != nil {
		t.Fatal(err)
	}
	for _, siteID := range []string{itSiteA, itSiteB} {
		if _, err := pool.Exec(ctx,
			"INSERT INTO user_site_access (user_id, site_id) VALUES ($1, $2)",
			itUser, siteID); err != nil {
			t.Fatal(err)
		}
	}

	store := NewStore(pool, 3*time.Second)
	issuedAt := time.Now()
	access := Access{
		UserID: itUser, Role: "viewer", SiteIDs: []string{itSiteA, itSiteB}, IssuedAt: issuedAt,
	}

	summary, err := store.Summary(ctx, access)
	if err != nil {
		t.Fatal(err)
	}
	wantTotals := StateCounts{Active: 2, Stale: 1, Disabled: 1, NeverSeen: 1, CertificateExpiring: 3}
	if summary.Totals != wantTotals {
		t.Fatalf("Totals = %+v, want %+v", summary.Totals, wantTotals)
	}
	if len(summary.Sites) != 2 ||
		summary.Sites[0].SiteID != itSiteA || summary.Sites[1].SiteID != itSiteB {
		t.Fatalf("unexpected site order: %+v", summary.Sites)
	}
	wantA := SiteSummary{
		SiteID:      itSiteA,
		StateCounts: StateCounts{Active: 1, Stale: 1, Disabled: 1, NeverSeen: 1, CertificateExpiring: 2},
	}
	wantB := SiteSummary{
		SiteID:      itSiteB,
		StateCounts: StateCounts{Active: 1, CertificateExpiring: 1},
	}
	if summary.Sites[0] != wantA || summary.Sites[1] != wantB {
		t.Fatalf("Sites = %+v, want %+v and %+v", summary.Sites, wantA, wantB)
	}

	// Scope naming only the inaccessible site discloses nothing.
	summary, err = store.Summary(ctx, Access{
		UserID: itUser, Role: "viewer", SiteIDs: []string{itSiteC}, IssuedAt: issuedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(summary.Sites) != 0 || summary.Totals != (StateCounts{}) {
		t.Fatalf("unauthorized site leaked into summary: %+v", summary)
	}

	// Detail lookup: stable order, bound, and state filter within scope.
	collectors, err := store.ListCollectors(ctx, access, CollectorFilter{SiteID: itSiteA})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 4 {
		t.Fatalf("len(collectors) = %d, want 4: %+v", len(collectors), collectors)
	}
	wantOrder := []string{"alpha", "beta", "delta", "gamma"}
	for i, id := range wantOrder {
		if collectors[i].CollectorID != id {
			t.Fatalf("collectors[%d] = %q, want %q: %+v", i, collectors[i].CollectorID, id, collectors)
		}
	}
	if collectors[0].State != StateActive || collectors[0].LastSeen == nil ||
		collectors[0].SilenceSeconds == nil || collectors[0].CertExpiresInDays == nil {
		t.Fatalf("unexpected active collector: %+v", collectors[0])
	}
	if collectors[2].State != StateNeverSeen || collectors[2].LastSeen != nil ||
		collectors[2].SilenceSeconds != nil {
		t.Fatalf("unexpected never_seen collector: %+v", collectors[2])
	}

	collectors, err = store.ListCollectors(ctx, access, CollectorFilter{SiteID: itSiteA, Limit: 2})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 2 || collectors[0].CollectorID != "alpha" || collectors[1].CollectorID != "beta" {
		t.Fatalf("bound not honored: %+v", collectors)
	}

	collectors, err = store.ListCollectors(ctx, access, CollectorFilter{State: StateStale})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 1 || collectors[0].CollectorID != "beta" {
		t.Fatalf("state filter mismatch: %+v", collectors)
	}

	// A filter naming an inaccessible site narrows to nothing.
	collectors, err = store.ListCollectors(ctx, access, CollectorFilter{SiteID: itSiteC})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 0 {
		t.Fatalf("inaccessible site leaked collectors: %+v", collectors)
	}

	// Token revocation takes effect without waiting for token expiry.
	if _, err := pool.Exec(ctx,
		"UPDATE users SET token_not_before = now() + interval '1 minute' WHERE user_id = $1",
		itUser); err != nil {
		t.Fatal(err)
	}
	summary, err = store.Summary(ctx, access)
	if err != nil {
		t.Fatal(err)
	}
	if len(summary.Sites) != 0 {
		t.Fatalf("revoked token retained summary access: %+v", summary)
	}
	collectors, err = store.ListCollectors(ctx, access, CollectorFilter{})
	if err != nil {
		t.Fatal(err)
	}
	if len(collectors) != 0 {
		t.Fatalf("revoked token retained detail access: %+v", collectors)
	}
}
