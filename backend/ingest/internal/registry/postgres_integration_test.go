//go:build integration

package registry

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	"github.com/Xore/analyseLaptop/backend/ingest/internal/ingest"
	"github.com/jackc/pgx/v5"
)

func TestPostgresAuthorizeAndMarkSeen(t *testing.T) {
	databaseURL := os.Getenv("SENTINEL_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Fatal("SENTINEL_TEST_DATABASE_URL is required for integration tests")
	}
	ctx := context.Background()
	registry, err := Open(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer registry.Close()

	_, err = registry.pool.Exec(ctx, `
		INSERT INTO sites (site_id, display_name)
		VALUES ('integration-site', 'Integration Site')
		ON CONFLICT (site_id) DO NOTHING;

		INSERT INTO collectors (
			site_id, collector_id, certificate_serial
		) VALUES (
			'integration-site', 'probe-01', '42'
		)
		ON CONFLICT (site_id, collector_id)
		DO UPDATE SET certificate_serial = EXCLUDED.certificate_serial,
		              disabled_at = NULL,
		              last_seen = NULL;
	`)
	if err != nil {
		t.Fatal(err)
	}

	observedAt := time.Now().UTC().Truncate(time.Microsecond)
	id := identity.Collector{
		SiteID:            "integration-site",
		CollectorID:       "probe-01",
		CertificateSerial: "42",
	}
	if err := registry.AuthorizeAndMarkSeen(ctx, id, observedAt); err != nil {
		t.Fatalf("AuthorizeAndMarkSeen() error = %v", err)
	}

	var lastSeen time.Time
	err = registry.pool.QueryRow(ctx, `
		SELECT last_seen
		  FROM collectors
		 WHERE site_id = $1 AND collector_id = $2
	`, id.SiteID, id.CollectorID).Scan(&lastSeen)
	if err != nil {
		t.Fatal(err)
	}
	if !lastSeen.Equal(observedAt) {
		t.Fatalf("last_seen = %s, want %s", lastSeen, observedAt)
	}
}

func TestPostgresRejectsMismatchedAndDisabledCollectors(t *testing.T) {
	databaseURL := os.Getenv("SENTINEL_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Fatal("SENTINEL_TEST_DATABASE_URL is required for integration tests")
	}
	ctx := context.Background()
	registry, err := Open(ctx, databaseURL)
	if err != nil {
		t.Fatal(err)
	}
	defer registry.Close()

	_, err = registry.pool.Exec(ctx, `
		INSERT INTO sites (site_id, display_name)
		VALUES ('disabled-site', 'Disabled Site')
		ON CONFLICT (site_id) DO NOTHING;

		INSERT INTO collectors (
			site_id, collector_id, certificate_serial, disabled_at
		) VALUES (
			'disabled-site', 'probe-01', '43', now()
		)
		ON CONFLICT (site_id, collector_id)
		DO UPDATE SET certificate_serial = EXCLUDED.certificate_serial,
		              disabled_at = now(),
		              last_seen = NULL;
	`)
	if err != nil {
		t.Fatal(err)
	}

	cases := []identity.Collector{
		{SiteID: "disabled-site", CollectorID: "probe-01", CertificateSerial: "43"},
		{SiteID: "disabled-site", CollectorID: "probe-01", CertificateSerial: "wrong"},
		{SiteID: "disabled-site", CollectorID: "unknown", CertificateSerial: "42"},
	}
	for _, id := range cases {
		err := registry.AuthorizeAndMarkSeen(ctx, id, time.Now().UTC())
		if !errors.Is(err, ingest.ErrCollectorUnauthorized) {
			t.Fatalf("AuthorizeAndMarkSeen(%#v) error = %v", id, err)
		}
	}

	var lastSeen *time.Time
	err = registry.pool.QueryRow(ctx, `
		SELECT last_seen
		  FROM collectors
		 WHERE site_id = 'disabled-site' AND collector_id = 'probe-01'
	`).Scan(&lastSeen)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		t.Fatal(err)
	}
	if lastSeen != nil {
		t.Fatalf("unauthorized request updated last_seen: %s", lastSeen)
	}
}
