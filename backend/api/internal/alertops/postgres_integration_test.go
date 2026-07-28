//go:build integration

package alertops

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	itSite     = "alertops-it-site"
	itSiteB    = "alertops-it-site-b"
	itOperator = "alertops-it-operator"
	itViewer   = "alertops-it-viewer"
)

func TestAlertLifecycleEnforcesScopeIdempotencyAndAudit(t *testing.T) {
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
		_, _ = pool.Exec(ctx, "DELETE FROM operational_audit_log WHERE site_id = ANY($1::text[])",
			[]string{itSite, itSiteB})
		_, _ = pool.Exec(ctx, "DELETE FROM alert_instances WHERE site_id = ANY($1::text[])",
			[]string{itSite, itSiteB})
		_, _ = pool.Exec(ctx, "DELETE FROM users WHERE user_id = ANY($1::text[])",
			[]string{itOperator, itViewer})
		for _, siteID := range []string{itSite, itSiteB} {
			_, _ = pool.Exec(ctx, "DELETE FROM sites WHERE site_id = $1", siteID)
		}
	}
	cleanup()
	defer cleanup()

	for _, siteID := range []string{itSite, itSiteB} {
		if _, err := pool.Exec(ctx,
			"INSERT INTO sites (site_id, display_name) VALUES ($1, 'alertops integration')",
			siteID); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := pool.Exec(ctx,
		"INSERT INTO users (user_id, role) VALUES ($1, 'operator'), ($2, 'viewer')",
		itOperator, itViewer); err != nil {
		t.Fatal(err)
	}
	// The operator can reach both sites; the viewer only the first.
	for _, siteID := range []string{itSite, itSiteB} {
		if _, err := pool.Exec(ctx,
			"INSERT INTO user_site_access (user_id, site_id) VALUES ($1, $2)",
			itOperator, siteID); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := pool.Exec(ctx,
		"INSERT INTO user_site_access (user_id, site_id) VALUES ($1, $2)",
		itViewer, itSite); err != nil {
		t.Fatal(err)
	}

	store := NewStore(pool, 3*time.Second)
	issuedAt := time.Now()
	operator := Access{
		UserID: itOperator, Role: "operator", SiteIDs: []string{itSite}, IssuedAt: issuedAt,
	}
	viewer := Access{
		UserID: itViewer, Role: "viewer", SiteIDs: []string{itSite}, IssuedAt: issuedAt,
	}
	firedAt := time.Now().Add(-time.Hour).UTC().Truncate(time.Millisecond)

	// Raise is authorized, durable, and audited.
	raise := RaiseInput{
		SiteID: itSite, DedupKey: "collector-unreachable:node-1",
		Severity: SeverityCritical, Summary: "collector node-1 stopped reporting",
		Source: "fleet-monitor", FiredAt: firedAt,
	}
	instance, created, err := store.Raise(ctx, operator, raise)
	if err != nil || !created {
		t.Fatalf("Raise() = %+v, %v, %v; want created", instance, created, err)
	}
	if instance.State != StateActive || instance.Version != 1 ||
		instance.AcknowledgedAt != nil || instance.SilencedUntil != nil {
		t.Fatalf("unexpected new instance: %+v", instance)
	}

	// Repeating the raise is idempotent and records nothing new.
	again, created, err := store.Raise(ctx, operator, raise)
	if err != nil || created {
		t.Fatalf("idempotent Raise() = %+v, %v, %v; want not created", again, created, err)
	}
	if again.ID != instance.ID || again.Version != 1 {
		t.Fatalf("idempotent raise changed instance: %+v vs %+v", again, instance)
	}

	// A viewer may list but not mutate.
	if _, _, err := store.Raise(ctx, viewer, raise); !errors.Is(err, ErrForbidden) {
		t.Fatalf("viewer Raise() = %v, want ErrForbidden", err)
	}
	if _, err := store.Acknowledge(ctx, viewer, instance.ID, AcknowledgeInput{ExpectedVersion: 1}); !errors.Is(err, ErrForbidden) {
		t.Fatalf("viewer Acknowledge() = %v, want ErrForbidden", err)
	}

	// Token scope outside the database grant discloses nothing.
	wideScope := Access{
		UserID: itViewer, Role: "viewer", SiteIDs: []string{itSiteB}, IssuedAt: issuedAt,
	}
	listed, err := store.List(ctx, wideScope, ListFilter{SiteID: itSiteB})
	if err != nil {
		t.Fatal(err)
	}
	if len(listed) != 0 {
		t.Fatalf("ungranted site leaked instances: %+v", listed)
	}

	// Acknowledge bumps the version, derives state, and audits.
	acked, err := store.Acknowledge(ctx, operator, instance.ID, AcknowledgeInput{ExpectedVersion: 1})
	if err != nil {
		t.Fatal(err)
	}
	if acked.State != StateAcknowledged || acked.Version != 2 ||
		acked.AcknowledgedAt == nil || acked.AcknowledgedBy == nil ||
		*acked.AcknowledgedBy != itOperator {
		t.Fatalf("unexpected acknowledged instance: %+v", acked)
	}

	// Retrying the acknowledge with the stale version is idempotent.
	retry, err := store.Acknowledge(ctx, operator, instance.ID, AcknowledgeInput{ExpectedVersion: 1})
	if err != nil {
		t.Fatal(err)
	}
	if retry.ID != acked.ID || retry.Version != 2 {
		t.Fatalf("acknowledge retry mutated instance: %+v", retry)
	}

	// A second active instance exercises list ordering and filters.
	other, created, err := store.Raise(ctx, operator, RaiseInput{
		SiteID: itSite, DedupKey: "cert-expiring:node-2",
		Severity: SeverityWarning, Summary: "certificate expires in 5 days",
		Source: "fleet-monitor", FiredAt: firedAt.Add(-time.Hour),
	})
	if err != nil || !created {
		t.Fatalf("second Raise() = %+v, %v, %v", other, created, err)
	}
	listed, err = store.List(ctx, viewer, ListFilter{SiteID: itSite})
	if err != nil {
		t.Fatal(err)
	}
	if len(listed) != 2 ||
		listed[0].ID != instance.ID || listed[1].ID != other.ID {
		t.Fatalf("list not in fired_at DESC order: %+v", listed)
	}
	listed, err = store.List(ctx, viewer, ListFilter{SiteID: itSite, State: StateAcknowledged})
	if err != nil {
		t.Fatal(err)
	}
	if len(listed) != 1 || listed[0].ID != instance.ID {
		t.Fatalf("state filter mismatch: %+v", listed)
	}
	listed, err = store.List(ctx, viewer, ListFilter{SiteID: itSite, Severity: SeverityWarning})
	if err != nil {
		t.Fatal(err)
	}
	if len(listed) != 1 || listed[0].ID != other.ID {
		t.Fatalf("severity filter mismatch: %+v", listed)
	}
	listed, err = store.List(ctx, viewer, ListFilter{SiteID: itSite, Limit: 1})
	if err != nil {
		t.Fatal(err)
	}
	if len(listed) != 1 || listed[0].ID != instance.ID {
		t.Fatalf("limit not honored: %+v", listed)
	}

	// Silence is time-bound, idempotent, and optimistic-concurrency checked.
	until := time.Now().Add(2 * time.Hour).UTC().Truncate(time.Millisecond)
	silenced, err := store.Silence(ctx, operator, other.ID, SilenceInput{
		ExpectedVersion: 1, Until: until, Reason: "planned deploy",
	})
	if err != nil {
		t.Fatal(err)
	}
	if silenced.State != StateSilenced || silenced.Version != 2 ||
		silenced.SilencedUntil == nil || !silenced.SilencedUntil.Equal(until) ||
		silenced.SilenceReason == nil || *silenced.SilenceReason != "planned deploy" {
		t.Fatalf("unexpected silenced instance: %+v", silenced)
	}
	repeat, err := store.Silence(ctx, operator, other.ID, SilenceInput{
		ExpectedVersion: 1, Until: until, Reason: "planned deploy",
	})
	if err != nil {
		t.Fatal(err)
	}
	if repeat.Version != 2 {
		t.Fatalf("silence repeat mutated instance: %+v", repeat)
	}
	if _, err := store.Silence(ctx, operator, other.ID, SilenceInput{
		ExpectedVersion: 1, Until: until.Add(time.Hour), Reason: "extended",
	}); !errors.Is(err, ErrConflict) {
		t.Fatalf("stale-version Silence() = %v, want ErrConflict", err)
	}

	// Mutations on inaccessible or missing instances disclose nothing.
	missingID := "00000000-0000-4000-8000-000000000000"
	if _, err := store.Acknowledge(ctx, operator, missingID, AcknowledgeInput{ExpectedVersion: 1}); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing Acknowledge() = %v, want ErrNotFound", err)
	}
	foreignScope := Access{
		UserID: itOperator, Role: "operator", SiteIDs: []string{itSiteB}, IssuedAt: issuedAt,
	}
	if _, err := store.Acknowledge(ctx, foreignScope, instance.ID, AcknowledgeInput{ExpectedVersion: 2}); !errors.Is(err, ErrNotFound) {
		t.Fatalf("out-of-scope Acknowledge() = %v, want ErrNotFound", err)
	}

	// Exactly the mutating operations left audit events, in version order.
	rows, err := pool.Query(ctx, `
		SELECT action, resource_version
		FROM operational_audit_log
		WHERE resource_type = 'alert_instance' AND resource_id = $1
		ORDER BY resource_version`, instance.ID)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	type auditEvent struct {
		action  string
		version int64
	}
	events := make([]auditEvent, 0)
	for rows.Next() {
		var event auditEvent
		if err := rows.Scan(&event.action, &event.version); err != nil {
			t.Fatal(err)
		}
		events = append(events, event)
	}
	if rows.Err() != nil {
		t.Fatal(rows.Err())
	}
	if len(events) != 2 ||
		events[0] != (auditEvent{"alert.raised", 1}) ||
		events[1] != (auditEvent{"alert.acknowledged", 2}) {
		t.Fatalf("unexpected audit events for %s: %+v", instance.ID, events)
	}

	var silenceAudits int
	if err := pool.QueryRow(ctx, `
		SELECT count(*) FROM operational_audit_log
		WHERE resource_type = 'alert_instance' AND resource_id = $1
		  AND action = 'alert.silenced' AND resource_version = 2`,
		other.ID).Scan(&silenceAudits); err != nil {
		t.Fatal(err)
	}
	if silenceAudits != 1 {
		t.Fatalf("silence audit count = %d, want 1", silenceAudits)
	}
}
