//go:build integration

package notifyops

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	itSite     = "notifyops-it-site"
	itSiteB    = "notifyops-it-site-b"
	itOperator = "notifyops-it-operator"
	itViewer   = "notifyops-it-viewer"
)

func TestOutboxLifecycleLeasesRetryAndDeadLetter(t *testing.T) {
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
		_, _ = pool.Exec(ctx, "DELETE FROM notification_outbox WHERE site_id = ANY($1::text[])",
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
			"INSERT INTO sites (site_id, display_name) VALUES ($1, 'notifyops integration')",
			siteID); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := pool.Exec(ctx,
		"INSERT INTO users (user_id, role) VALUES ($1, 'operator'), ($2, 'viewer')",
		itOperator, itViewer); err != nil {
		t.Fatal(err)
	}
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
	store.Backoff = func(int) time.Duration { return time.Minute }
	issuedAt := time.Now()
	operator := Access{
		UserID: itOperator, Role: "operator", SiteIDs: []string{itSite}, IssuedAt: issuedAt,
	}
	viewer := Access{
		UserID: itViewer, Role: "viewer", SiteIDs: []string{itSite}, IssuedAt: issuedAt,
	}
	enqueue := func(channel, key string, maxAttempts int) Notification {
		n, created, err := store.Enqueue(ctx, operator, EnqueueInput{
			SiteID: itSite, Channel: channel, DedupKey: key,
			Payload:     json.RawMessage(`{"key":"` + key + `"}`),
			MaxAttempts: maxAttempts,
		})
		if err != nil || !created {
			t.Fatalf("Enqueue(%s) = %+v, %v, %v; want created", key, n, created, err)
		}
		if n.Status != StatusPending || n.Version != 1 || n.Attempts != 0 {
			t.Fatalf("unexpected new notification: %+v", n)
		}
		return n
	}

	n1 := enqueue(ChannelWebhook, "k1", 0)
	n2 := enqueue(ChannelSMTP, "k2", 0)
	n3 := enqueue(ChannelWebhook, "k3", 0)
	n4 := enqueue(ChannelSMTP, "k4", 1)

	// Enqueue is idempotent per (site, channel, dedup key).
	again, created, err := store.Enqueue(ctx, operator, EnqueueInput{
		SiteID: itSite, Channel: ChannelWebhook, DedupKey: "k1",
		Payload: json.RawMessage(`{"key":"k1"}`),
	})
	if err != nil || created || again.ID != n1.ID || again.Version != 1 {
		t.Fatalf("idempotent Enqueue() = %+v, %v, %v", again, created, err)
	}

	// A viewer may not operate the outbox.
	if _, _, err := store.Enqueue(ctx, viewer, EnqueueInput{
		SiteID: itSite, Channel: ChannelWebhook, DedupKey: "kv",
		Payload: json.RawMessage(`{}`),
	}); !errors.Is(err, ErrForbidden) {
		t.Fatalf("viewer Enqueue() = %v, want ErrForbidden", err)
	}

	// Deterministic pending order: earlier scheduled attempt first.
	for _, stmt := range []struct {
		id  string
		set string
	}{
		{n2.ID, "now() - interval '1 minute'"},
		{n3.ID, "now() - interval '2 minutes'"},
	} {
		if _, err := pool.Exec(ctx,
			"UPDATE notification_outbox SET next_attempt_at = "+stmt.set+
				" WHERE notification_id = $1", stmt.id); err != nil {
			t.Fatal(err)
		}
	}
	claimed, err := store.Claim(ctx, operator, ClaimInput{WorkerID: "worker-1", Limit: 2, Lease: 5 * time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if len(claimed) != 2 || claimed[0].ID != n3.ID || claimed[1].ID != n2.ID {
		t.Fatalf("claim order = %+v, want [%s %s]", claimed, n3.ID, n2.ID)
	}
	for _, n := range claimed {
		if n.Status != StatusLeased || n.LeasedBy == nil || *n.LeasedBy != "worker-1" ||
			n.LeaseExpires == nil || n.Version != 2 {
			t.Fatalf("unexpected leased notification: %+v", n)
		}
	}

	// A concurrent worker never receives rows under an unexpired lease.
	second, err := store.Claim(ctx, operator, ClaimInput{WorkerID: "worker-2", Limit: 10, Lease: 5 * time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if len(second) != 2 {
		t.Fatalf("second claim = %+v, want the two unleased rows", second)
	}
	claimedIDs := map[string]Notification{}
	for _, n := range second {
		claimedIDs[n.ID] = n
	}
	if _, ok := claimedIDs[n1.ID]; !ok {
		t.Fatalf("second claim missing %s: %+v", n1.ID, second)
	}
	n1Claimed := claimedIDs[n1.ID]
	n4Claimed := claimedIDs[n4.ID]

	// Lease owner and optimistic version are enforced on completion.
	if _, err := store.Complete(ctx, operator, n3.ID, CompleteInput{
		ExpectedVersion: 2, WorkerID: "worker-2", Outcome: OutcomeSuccess,
	}); !errors.Is(err, ErrConflict) {
		t.Fatalf("foreign worker Complete() = %v, want ErrConflict", err)
	}
	if _, err := store.Complete(ctx, operator, n3.ID, CompleteInput{
		ExpectedVersion: 9, WorkerID: "worker-1", Outcome: OutcomeSuccess,
	}); !errors.Is(err, ErrConflict) {
		t.Fatalf("stale version Complete() = %v, want ErrConflict", err)
	}

	// A retryable failure reschedules with the injected backoff.
	before := time.Now()
	retried, err := store.Complete(ctx, operator, n3.ID, CompleteInput{
		ExpectedVersion: 2, WorkerID: "worker-1",
		Outcome: OutcomeRetryableFailure, Detail: "smtp timeout",
	})
	if err != nil {
		t.Fatal(err)
	}
	if retried.Status != StatusPending || retried.Attempts != 1 || retried.Version != 3 ||
		retried.LeasedBy != nil || retried.LastError == nil || *retried.LastError != "smtp timeout" {
		t.Fatalf("unexpected retry state: %+v", retried)
	}
	if retried.NextAttemptAt.Before(before.Add(50*time.Second)) ||
		retried.NextAttemptAt.After(before.Add(70*time.Second)) {
		t.Fatalf("backoff schedule = %v, want about one minute", retried.NextAttemptAt)
	}

	// The rescheduled row is not claimable before it is due.
	due, err := store.Claim(ctx, operator, ClaimInput{WorkerID: "worker-3", Limit: 10, Lease: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if len(due) != 0 {
		t.Fatalf("undue notification claimed: %+v", due)
	}
	if _, err := pool.Exec(ctx,
		"UPDATE notification_outbox SET next_attempt_at = now() - interval '1 second' WHERE notification_id = $1",
		n3.ID); err != nil {
		t.Fatal(err)
	}
	due, err = store.Claim(ctx, operator, ClaimInput{WorkerID: "worker-3", Limit: 10, Lease: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if len(due) != 1 || due[0].ID != n3.ID || due[0].Version != 4 {
		t.Fatalf("due claim = %+v", due)
	}

	// A permanent failure dead-letters immediately.
	dead, err := store.Complete(ctx, operator, n3.ID, CompleteInput{
		ExpectedVersion: 4, WorkerID: "worker-3",
		Outcome: OutcomePermanentFailure, Detail: "recipient rejected",
	})
	if err != nil {
		t.Fatal(err)
	}
	if dead.Status != StatusDead || dead.Attempts != 2 || dead.LeasedBy != nil {
		t.Fatalf("unexpected dead state: %+v", dead)
	}

	// A retryable failure on the final allowed attempt dead-letters too.
	exhausted, err := store.Complete(ctx, operator, n4.ID, CompleteInput{
		ExpectedVersion: n4Claimed.Version, WorkerID: "worker-2",
		Outcome: OutcomeRetryableFailure, Detail: "connection refused",
	})
	if err != nil {
		t.Fatal(err)
	}
	if exhausted.Status != StatusDead || exhausted.Attempts != 1 {
		t.Fatalf("unexpected exhaustion state: %+v", exhausted)
	}

	// Success delivers and clears the lease and error.
	delivered, err := store.Complete(ctx, operator, n1.ID, CompleteInput{
		ExpectedVersion: n1Claimed.Version, WorkerID: "worker-2", Outcome: OutcomeSuccess,
	})
	if err != nil {
		t.Fatal(err)
	}
	if delivered.Status != StatusDelivered || delivered.DeliveredAt == nil ||
		delivered.Attempts != 1 || delivered.LeasedBy != nil || delivered.LastError != nil {
		t.Fatalf("unexpected delivered state: %+v", delivered)
	}

	// Reporting on a terminal notification is an idempotent no-op.
	repeat, err := store.Complete(ctx, operator, n1.ID, CompleteInput{
		ExpectedVersion: 1, WorkerID: "worker-2", Outcome: OutcomeSuccess,
	})
	if err != nil {
		t.Fatal(err)
	}
	if repeat.Status != StatusDelivered || repeat.Version != delivered.Version {
		t.Fatalf("terminal repeat mutated notification: %+v", repeat)
	}

	// An expired lease is recoverable by another worker.
	if _, err := pool.Exec(ctx,
		"UPDATE notification_outbox SET lease_expires_at = now() - interval '1 minute' WHERE notification_id = $1",
		n2.ID); err != nil {
		t.Fatal(err)
	}
	recovered, err := store.Claim(ctx, operator, ClaimInput{WorkerID: "worker-4", Limit: 10, Lease: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if len(recovered) != 1 || recovered[0].ID != n2.ID ||
		recovered[0].LeasedBy == nil || *recovered[0].LeasedBy != "worker-4" {
		t.Fatalf("stale lease not recovered: %+v", recovered)
	}

	// Attempt history is append-only, ordered, and exact.
	attempts, err := store.ListAttempts(ctx, operator, n3.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(attempts) != 2 ||
		attempts[0].Number != 1 || attempts[0].Outcome != OutcomeRetryableFailure ||
		attempts[0].Detail != "smtp timeout" || attempts[0].AttemptedBy != "worker-1" ||
		attempts[1].Number != 2 || attempts[1].Outcome != OutcomePermanentFailure {
		t.Fatalf("unexpected attempt history: %+v", attempts)
	}
	attempts, err = store.ListAttempts(ctx, operator, n1.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(attempts) != 1 || attempts[0].Outcome != OutcomeSuccess {
		t.Fatalf("terminal repeat recorded an attempt: %+v", attempts)
	}
	if _, err := pool.Exec(ctx,
		"UPDATE notification_attempts SET outcome = 'success' WHERE notification_id = $1",
		n3.ID); err == nil {
		t.Fatal("append-only trigger allowed an attempt update")
	}

	// Inaccessible sites disclose nothing.
	foreign := Access{
		UserID: itOperator, Role: "operator", SiteIDs: []string{itSiteB}, IssuedAt: issuedAt,
	}
	claimed, err = store.Claim(ctx, foreign, ClaimInput{WorkerID: "worker-5", Limit: 10, Lease: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	if len(claimed) != 0 {
		t.Fatalf("out-of-scope claim leaked notifications: %+v", claimed)
	}
	if _, err := store.Complete(ctx, foreign, n2.ID, CompleteInput{
		ExpectedVersion: 3, WorkerID: "worker-5", Outcome: OutcomeSuccess,
	}); !errors.Is(err, ErrNotFound) {
		t.Fatalf("out-of-scope Complete() = %v, want ErrNotFound", err)
	}

	// A site-authorized viewer may read attempt history.
	history, err := store.ListAttempts(ctx, viewer, n1.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) != 1 || history[0].Outcome != OutcomeSuccess {
		t.Fatalf("viewer attempt history = %+v", history)
	}
}
