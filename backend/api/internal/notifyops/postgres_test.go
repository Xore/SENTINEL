package notifyops

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

var validEnqueue = EnqueueInput{
	SiteID:   "site-a",
	Channel:  ChannelWebhook,
	DedupKey: "alert:node-1:critical",
	Payload:  json.RawMessage(`{"alert_id":"00000000-0000-4000-8000-000000000000","severity":"critical"}`),
}

func TestValidateEnqueue(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*EnqueueInput)
		valid  bool
	}{
		{"valid", func(*EnqueueInput) {}, true},
		{"trims fields", func(i *EnqueueInput) {
			i.SiteID = " site-a "
			i.Channel = " webhook "
			i.DedupKey = " key "
		}, true},
		{"bad site", func(i *EnqueueInput) { i.SiteID = "Bad_Site" }, false},
		{"bad channel", func(i *EnqueueInput) { i.Channel = "pagerduty" }, false},
		{"empty dedup key", func(i *EnqueueInput) { i.DedupKey = " " }, false},
		{"long dedup key", func(i *EnqueueInput) { i.DedupKey = strings.Repeat("k", maxDedupKeyLength+1) }, false},
		{"empty payload", func(i *EnqueueInput) { i.Payload = nil }, false},
		{"oversize payload", func(i *EnqueueInput) {
			i.Payload = json.RawMessage(`{"k":"` + strings.Repeat("v", maxPayloadBytes) + `"}`)
		}, false},
		{"payload array rejected", func(i *EnqueueInput) { i.Payload = json.RawMessage(`[]`) }, false},
		{"payload scalar rejected", func(i *EnqueueInput) { i.Payload = json.RawMessage(`"x"`) }, false},
		{"payload malformed", func(i *EnqueueInput) { i.Payload = json.RawMessage(`{`) }, false},
		{"max attempts negative", func(i *EnqueueInput) { i.MaxAttempts = -1 }, false},
		{"max attempts too high", func(i *EnqueueInput) { i.MaxAttempts = maxMaxAttempts + 1 }, false},
		{"max attempts explicit", func(i *EnqueueInput) { i.MaxAttempts = 3 }, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			input := validEnqueue
			tt.mutate(&input)
			_, err := ValidateEnqueue(input)
			if tt.valid != (err == nil) {
				t.Fatalf("ValidateEnqueue() err = %v, valid = %v", err, tt.valid)
			}
		})
	}

	normalized, err := ValidateEnqueue(validEnqueue)
	if err != nil {
		t.Fatal(err)
	}
	if normalized.MaxAttempts != defaultMaxAttempts {
		t.Fatalf("MaxAttempts = %d, want default %d", normalized.MaxAttempts, defaultMaxAttempts)
	}
}

func TestValidateClaim(t *testing.T) {
	normalized, err := ValidateClaim(ClaimInput{WorkerID: "worker-1"})
	if err != nil {
		t.Fatal(err)
	}
	if normalized.Limit != defaultClaimLimit || normalized.Lease != defaultLeaseSeconds*time.Second {
		t.Fatalf("defaults not applied: %+v", normalized)
	}
	invalid := []ClaimInput{
		{WorkerID: " "},
		{WorkerID: strings.Repeat("w", maxWorkerIDLength+1)},
		{WorkerID: "w", Limit: -1},
		{WorkerID: "w", Limit: maxClaimLimit + 1},
		{WorkerID: "w", Lease: time.Millisecond},
		{WorkerID: "w", Lease: maxLeaseSeconds*time.Second + time.Second},
	}
	for _, input := range invalid {
		if _, err := ValidateClaim(input); !errors.Is(err, ErrInvalid) {
			t.Fatalf("ValidateClaim(%+v) err = %v, want ErrInvalid", input, err)
		}
	}
}

func TestValidateComplete(t *testing.T) {
	valid := CompleteInput{ExpectedVersion: 1, WorkerID: "worker-1", Outcome: OutcomeRetryableFailure, Detail: "timeout"}
	if _, err := ValidateComplete(valid); err != nil {
		t.Fatal(err)
	}
	invalid := []CompleteInput{
		{ExpectedVersion: 0, WorkerID: "w", Outcome: OutcomeSuccess},
		{ExpectedVersion: 1, WorkerID: "", Outcome: OutcomeSuccess},
		{ExpectedVersion: 1, WorkerID: "w", Outcome: "unknown"},
		{ExpectedVersion: 1, WorkerID: "w", Outcome: OutcomeSuccess, Detail: strings.Repeat("d", maxDetailLength+1)},
	}
	for _, input := range invalid {
		if _, err := ValidateComplete(input); !errors.Is(err, ErrInvalid) {
			t.Fatalf("ValidateComplete(%+v) err = %v, want ErrInvalid", input, err)
		}
	}
}

func TestDefaultBackoffIsDeterministicExponentialAndCapped(t *testing.T) {
	want := []time.Duration{
		30 * time.Second,
		time.Minute,
		2 * time.Minute,
		4 * time.Minute,
		8 * time.Minute,
		16 * time.Minute,
		32 * time.Minute,
		time.Hour,
		time.Hour,
	}
	for attempt := 1; attempt <= len(want); attempt++ {
		if got := DefaultBackoff(attempt); got != want[attempt-1] {
			t.Fatalf("DefaultBackoff(%d) = %v, want %v", attempt, got, want[attempt-1])
		}
	}
}

func TestNilStoreReturnsErrUnavailable(t *testing.T) {
	store := NewStore(nil, time.Second)
	access := Access{UserID: "u", Role: "admin", SiteIDs: []string{"site-a"}, IssuedAt: time.Now()}

	if _, _, err := store.Enqueue(context.Background(), access, validEnqueue); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Enqueue() = %v, want ErrUnavailable", err)
	}
	if _, err := store.Claim(context.Background(), access, ClaimInput{WorkerID: "w"}); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Claim() = %v, want ErrUnavailable", err)
	}
	if _, err := store.Complete(context.Background(), access, "x", CompleteInput{}); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Complete() = %v, want ErrUnavailable", err)
	}
	if _, err := store.ListAttempts(context.Background(), access, "x"); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("ListAttempts() = %v, want ErrUnavailable", err)
	}
}

func TestRoleEnforcementBeforeValidation(t *testing.T) {
	// pgxpool.New does not connect eagerly; role rejection happens before any
	// database use, so the unreachable pool is never touched.
	pool, err := pgxpool.New(context.Background(), "postgres://127.0.0.1:1/unreachable")
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	store := NewStore(pool, time.Second)
	viewer := Access{UserID: "u", Role: "viewer", SiteIDs: []string{"site-a"}, IssuedAt: time.Now()}

	if _, _, err := store.Enqueue(context.Background(), viewer, validEnqueue); !errors.Is(err, ErrForbidden) {
		t.Fatalf("Enqueue() = %v, want ErrForbidden", err)
	}
	if _, err := store.Claim(context.Background(), viewer, ClaimInput{WorkerID: "w"}); !errors.Is(err, ErrForbidden) {
		t.Fatalf("Claim() = %v, want ErrForbidden", err)
	}
	if _, err := store.Complete(context.Background(), viewer, "x", CompleteInput{}); !errors.Is(err, ErrForbidden) {
		t.Fatalf("Complete() = %v, want ErrForbidden", err)
	}
}

func TestNotificationJSONShape(t *testing.T) {
	encoded, err := json.Marshal(Notification{
		ID:            "00000000-0000-4000-8000-000000000000",
		SiteID:        "site-a",
		Channel:       ChannelSMTP,
		DedupKey:      "key",
		Payload:       json.RawMessage(`{"severity":"warning"}`),
		Status:        StatusPending,
		Attempts:      0,
		MaxAttempts:   defaultMaxAttempts,
		NextAttemptAt: time.Date(2026, 7, 28, 12, 0, 0, 0, time.UTC),
		Version:       1,
		CreatedBy:     "pipeline",
		CreatedAt:     time.Date(2026, 7, 28, 12, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != `{"id":"00000000-0000-4000-8000-000000000000",`+
		`"site_id":"site-a","channel":"smtp","dedup_key":"key",`+
		`"payload":{"severity":"warning"},"status":"pending","attempts":0,`+
		`"max_attempts":8,"next_attempt_at":"2026-07-28T12:00:00Z",`+
		`"leased_by":null,"lease_expires_at":null,"last_error":null,`+
		`"version":1,"created_by":"pipeline","created_at":"2026-07-28T12:00:00Z",`+
		`"delivered_at":null}` {
		t.Fatalf("unexpected JSON: %s", encoded)
	}
}

func TestValidUUID(t *testing.T) {
	id, err := newUUID()
	if err != nil {
		t.Fatal(err)
	}
	if !validUUID(id) {
		t.Fatalf("newUUID() = %q rejected by validUUID", id)
	}
	if validUUID("00000000-0000-4000-8000-00000000000G") {
		t.Fatal("invalid UUID accepted")
	}
}
