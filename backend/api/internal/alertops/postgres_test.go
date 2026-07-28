package alertops

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

var validRaise = RaiseInput{
	SiteID:   "site-a",
	DedupKey: "collector-unreachable:node-1",
	Severity: SeverityCritical,
	Summary:  "collector node-1 stopped reporting",
	Source:   "fleet-monitor",
	FiredAt:  time.Date(2026, 7, 28, 12, 0, 0, 0, time.UTC),
}

func TestValidateRaise(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*RaiseInput)
		valid  bool
	}{
		{"valid", func(*RaiseInput) {}, true},
		{"trims fields", func(i *RaiseInput) {
			i.SiteID = " site-a "
			i.DedupKey = " key "
			i.Summary = " summary "
			i.Source = " source "
		}, true},
		{"bad site", func(i *RaiseInput) { i.SiteID = "Bad_Site" }, false},
		{"empty dedup key", func(i *RaiseInput) { i.DedupKey = " " }, false},
		{"long dedup key", func(i *RaiseInput) { i.DedupKey = strings.Repeat("k", maxDedupKeyLength+1) }, false},
		{"bad severity", func(i *RaiseInput) { i.Severity = "page" }, false},
		{"empty summary", func(i *RaiseInput) { i.Summary = "" }, false},
		{"long summary", func(i *RaiseInput) { i.Summary = strings.Repeat("s", maxSummaryLength+1) }, false},
		{"empty source", func(i *RaiseInput) { i.Source = "" }, false},
		{"long source", func(i *RaiseInput) { i.Source = strings.Repeat("s", maxSourceLength+1) }, false},
		{"zero fired_at", func(i *RaiseInput) { i.FiredAt = time.Time{} }, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			input := validRaise
			tt.mutate(&input)
			_, err := ValidateRaise(input)
			if tt.valid != (err == nil) {
				t.Fatalf("ValidateRaise() err = %v, valid = %v", err, tt.valid)
			}
		})
	}

	normalized, err := ValidateRaise(RaiseInput{
		SiteID: " site-a ", DedupKey: " key ", Severity: " info ",
		Summary: " s ", Source: " src ",
		FiredAt: time.Date(2026, 7, 28, 12, 0, 0, 0, time.FixedZone("x", 3600)),
	})
	if err != nil {
		t.Fatal(err)
	}
	if normalized.SiteID != "site-a" || normalized.DedupKey != "key" ||
		normalized.Summary != "s" || normalized.Source != "src" ||
		normalized.FiredAt.Location() != time.UTC {
		t.Fatalf("not normalized: %+v", normalized)
	}
}

func TestValidateAcknowledge(t *testing.T) {
	if err := ValidateAcknowledge(AcknowledgeInput{ExpectedVersion: 1}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateAcknowledge(AcknowledgeInput{ExpectedVersion: 0}); !errors.Is(err, ErrInvalid) {
		t.Fatalf("err = %v, want ErrInvalid", err)
	}
}

func TestValidateSilence(t *testing.T) {
	now := time.Date(2026, 7, 28, 12, 0, 0, 0, time.UTC)
	tests := []struct {
		name  string
		input SilenceInput
		valid bool
	}{
		{"valid", SilenceInput{ExpectedVersion: 1, Until: now.Add(time.Hour), Reason: "deploy"}, true},
		{"bad version", SilenceInput{ExpectedVersion: 0, Until: now.Add(time.Hour), Reason: "deploy"}, false},
		{"empty reason", SilenceInput{ExpectedVersion: 1, Until: now.Add(time.Hour), Reason: " "}, false},
		{"long reason", SilenceInput{ExpectedVersion: 1, Until: now.Add(time.Hour), Reason: strings.Repeat("r", maxSilenceReasonLength+1)}, false},
		{"until in past", SilenceInput{ExpectedVersion: 1, Until: now.Add(-time.Minute), Reason: "deploy"}, false},
		{"until now", SilenceInput{ExpectedVersion: 1, Until: now, Reason: "deploy"}, false},
		{"until beyond bound", SilenceInput{ExpectedVersion: 1, Until: now.Add(maxSilenceDuration + time.Minute), Reason: "deploy"}, false},
		{"until at bound", SilenceInput{ExpectedVersion: 1, Until: now.Add(maxSilenceDuration), Reason: "deploy"}, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := ValidateSilence(tt.input, now)
			if tt.valid != (err == nil) {
				t.Fatalf("ValidateSilence() err = %v, valid = %v", err, tt.valid)
			}
		})
	}
}

func TestValidateList(t *testing.T) {
	filter, err := ValidateList(ListFilter{SiteID: "site-a"})
	if err != nil {
		t.Fatal(err)
	}
	if filter.State != "all" || filter.Limit != defaultListLimit {
		t.Fatalf("defaults not applied: %+v", filter)
	}
	for _, state := range []string{"all", StateActive, StateAcknowledged, StateSilenced} {
		if _, err := ValidateList(ListFilter{SiteID: "site-a", State: state}); err != nil {
			t.Fatalf("state %q rejected: %v", state, err)
		}
	}
	for _, severity := range []string{"", SeverityInfo, SeverityWarning, SeverityCritical} {
		if _, err := ValidateList(ListFilter{SiteID: "site-a", Severity: severity}); err != nil {
			t.Fatalf("severity %q rejected: %v", severity, err)
		}
	}
	invalid := []ListFilter{
		{SiteID: ""},
		{SiteID: "Bad_Site"},
		{SiteID: "site-a", State: "bogus"},
		{SiteID: "site-a", Severity: "page"},
		{SiteID: "site-a", Limit: -1},
		{SiteID: "site-a", Limit: maxListLimit + 1},
	}
	for _, filter := range invalid {
		if _, err := ValidateList(filter); !errors.Is(err, ErrInvalid) {
			t.Fatalf("ValidateList(%+v) err = %v, want ErrInvalid", filter, err)
		}
	}
}

func TestCanMutate(t *testing.T) {
	for _, role := range []string{"operator", "analyst", "admin", "ot-operator"} {
		if !CanMutate(role) {
			t.Fatalf("role %q cannot mutate", role)
		}
	}
	for _, role := range []string{"viewer", "", "superadmin"} {
		if CanMutate(role) {
			t.Fatalf("role %q can mutate", role)
		}
	}
}

func TestNilStoreReturnsErrUnavailable(t *testing.T) {
	store := NewStore(nil, time.Second)
	access := Access{UserID: "u", Role: "admin", SiteIDs: []string{"site-a"}, IssuedAt: time.Now()}

	if _, _, err := store.Raise(context.Background(), access, validRaise); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Raise() = %v, want ErrUnavailable", err)
	}
	if _, err := store.List(context.Background(), access, ListFilter{SiteID: "site-a"}); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("List() = %v, want ErrUnavailable", err)
	}
	if _, err := store.Acknowledge(context.Background(), access, "x", AcknowledgeInput{ExpectedVersion: 1}); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Acknowledge() = %v, want ErrUnavailable", err)
	}
	if _, err := store.Silence(context.Background(), access, "x", SilenceInput{
		ExpectedVersion: 1, Until: time.Now().Add(time.Hour), Reason: "deploy",
	}); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Silence() = %v, want ErrUnavailable", err)
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

	if _, _, err := store.Raise(context.Background(), viewer, validRaise); !errors.Is(err, ErrForbidden) {
		t.Fatalf("Raise() = %v, want ErrForbidden", err)
	}
	if _, err := store.Acknowledge(context.Background(), viewer, "x", AcknowledgeInput{}); !errors.Is(err, ErrForbidden) {
		t.Fatalf("Acknowledge() = %v, want ErrForbidden", err)
	}
	if _, err := store.Silence(context.Background(), viewer, "x", SilenceInput{}); !errors.Is(err, ErrForbidden) {
		t.Fatalf("Silence() = %v, want ErrForbidden", err)
	}
}

func TestInstanceJSONShape(t *testing.T) {
	encoded, err := json.Marshal(Instance{
		ID:        "00000000-0000-4000-8000-000000000000",
		SiteID:    "site-a",
		DedupKey:  "key",
		Severity:  SeverityWarning,
		Summary:   "summary",
		Source:    "source",
		State:     StateActive,
		FiredAt:   time.Date(2026, 7, 28, 12, 0, 0, 0, time.UTC),
		Version:   1,
		CreatedBy: "pipeline",
		CreatedAt: time.Date(2026, 7, 28, 12, 0, 1, 0, time.UTC),
	})
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != `{"id":"00000000-0000-4000-8000-000000000000",`+
		`"site_id":"site-a","dedup_key":"key","severity":"warning",`+
		`"summary":"summary","source":"source","state":"active",`+
		`"fired_at":"2026-07-28T12:00:00Z","version":1,"created_by":"pipeline",`+
		`"created_at":"2026-07-28T12:00:01Z","acknowledged_at":null,`+
		`"acknowledged_by":null,"silenced_until":null,"silenced_by":null,`+
		`"silence_reason":null}` {
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
	for _, bad := range []string{"", "x", "00000000-0000-4000-8000-00000000000G", "00000000000040008000000000000000"} {
		if validUUID(bad) {
			t.Fatalf("validUUID(%q) = true", bad)
		}
	}
}
