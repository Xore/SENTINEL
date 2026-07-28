package fleetops

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestNormalizeFilterClampsLimit(t *testing.T) {
	tests := []struct {
		name  string
		limit int
		want  int
	}{
		{"zero selects default", 0, defaultCollectorLimit},
		{"negative selects default", -5, defaultCollectorLimit},
		{"one kept", 1, 1},
		{"within bounds kept", defaultCollectorLimit, defaultCollectorLimit},
		{"maximum kept", maxCollectorLimit, maxCollectorLimit},
		{"above maximum clamped", maxCollectorLimit + 1, maxCollectorLimit},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			filter, err := normalizeFilter(CollectorFilter{Limit: tt.limit})
			if err != nil {
				t.Fatal(err)
			}
			if filter.Limit != tt.want {
				t.Fatalf("Limit = %d, want %d", filter.Limit, tt.want)
			}
		})
	}
}

func TestNormalizeFilterValidatesState(t *testing.T) {
	for _, state := range []string{"", StateActive, StateStale, StateDisabled, StateNeverSeen} {
		if _, err := normalizeFilter(CollectorFilter{State: state}); err != nil {
			t.Fatalf("state %q rejected: %v", state, err)
		}
	}
	if _, err := normalizeFilter(CollectorFilter{State: "bogus"}); !errors.Is(err, ErrInvalidFilter) {
		t.Fatalf("err = %v, want ErrInvalidFilter", err)
	}
}

func TestNilPoolReturnsErrUnavailable(t *testing.T) {
	store := NewStore(nil, time.Second)
	access := Access{UserID: "u", Role: "viewer", SiteIDs: []string{"site-a"}, IssuedAt: time.Now()}

	if err := store.Ping(context.Background()); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Ping() = %v, want ErrUnavailable", err)
	}
	if _, err := store.Summary(context.Background(), access); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Summary() = %v, want ErrUnavailable", err)
	}
	if _, err := store.ListCollectors(context.Background(), access, CollectorFilter{}); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("ListCollectors() = %v, want ErrUnavailable", err)
	}
}

func TestEmptyScopeReturnsEmptyWithoutQuerying(t *testing.T) {
	// pgxpool.New does not connect eagerly; an early return before any query
	// proves the empty-scope path never touches the database.
	pool, err := pgxpool.New(context.Background(), "postgres://127.0.0.1:1/unreachable")
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	store := NewStore(pool, time.Second)
	access := Access{UserID: "u", Role: "viewer", SiteIDs: nil, IssuedAt: time.Now()}

	summary, err := store.Summary(context.Background(), access)
	if err != nil {
		t.Fatal(err)
	}
	if summary.Sites == nil || len(summary.Sites) != 0 || summary.Totals != (StateCounts{}) {
		t.Fatalf("unexpected summary: %+v", summary)
	}

	collectors, err := store.ListCollectors(context.Background(), access, CollectorFilter{})
	if err != nil {
		t.Fatal(err)
	}
	if collectors == nil || len(collectors) != 0 {
		t.Fatalf("unexpected collectors: %+v", collectors)
	}
}

func TestCollectorDetailQueryShape(t *testing.T) {
	access := Access{
		UserID: "u", Role: "viewer", SiteIDs: []string{"site-a"}, IssuedAt: time.Now(),
	}

	query, args := collectorDetailQuery(access, CollectorFilter{Limit: defaultCollectorLimit})
	if len(args) != 6 {
		t.Fatalf("len(args) = %d, want 6", len(args))
	}
	if !strings.Contains(query, "ORDER BY c.site_id, c.collector_id\n\t\tLIMIT $6") {
		t.Fatalf("missing deterministic order and bound:\n%s", query)
	}
	if strings.Contains(query, "$7") {
		t.Fatalf("unexpected optional parameter:\n%s", query)
	}

	query, args = collectorDetailQuery(access, CollectorFilter{
		SiteID: "site-a", State: StateStale, Limit: 7,
	})
	if len(args) != 8 {
		t.Fatalf("len(args) = %d, want 8", len(args))
	}
	if args[4] != int64(staleThreshold/time.Second) || args[5] != 7 ||
		args[6] != "site-a" || args[7] != StateStale {
		t.Fatalf("unexpected args: %v", args)
	}
	if !strings.Contains(query, "AND c.site_id = $7") {
		t.Fatalf("missing site filter:\n%s", query)
	}
	if !strings.Contains(query, "END = $8") {
		t.Fatalf("missing state filter:\n%s", query)
	}
}

func TestSummaryJSONShape(t *testing.T) {
	encoded, err := json.Marshal(Summary{Sites: make([]SiteSummary, 0)})
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != `{"totals":{"active":0,"stale":0,"disabled":0,`+
		`"never_seen":0,"certificate_expiring":0},"sites":[]}` {
		t.Fatalf("unexpected JSON: %s", encoded)
	}
}

func TestCollectorDetailJSONShape(t *testing.T) {
	encoded, err := json.Marshal(CollectorDetail{
		SiteID:      "site-a",
		CollectorID: "node-1",
		State:       StateNeverSeen,
		EnrolledAt:  time.Date(2026, 7, 26, 10, 0, 0, 0, time.UTC),
	})
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != `{"site_id":"site-a","collector_id":"node-1",`+
		`"state":"never_seen","last_seen":null,"silence_seconds":null,`+
		`"enrolled_at":"2026-07-26T10:00:00Z","certificate_not_after":null,`+
		`"cert_expires_in_days":null}` {
		t.Fatalf("unexpected JSON: %s", encoded)
	}
}
