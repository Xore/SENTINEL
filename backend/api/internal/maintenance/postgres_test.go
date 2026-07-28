package maintenance

import (
	"errors"
	"testing"
	"time"
)

func TestValidateCreate(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	valid := CreateInput{
		SiteID:   "site-a",
		StartsAt: now,
		EndsAt:   now.Add(time.Hour),
		Reason:   " planned work ",
	}
	got, err := ValidateCreate(valid)
	if err != nil {
		t.Fatalf("ValidateCreate() error = %v", err)
	}
	if got.Reason != "planned work" || got.SiteID != "site-a" {
		t.Fatalf("ValidateCreate() = %+v", got)
	}

	tests := []CreateInput{
		{SiteID: "INVALID", StartsAt: now, EndsAt: now.Add(time.Hour), Reason: "work"},
		{SiteID: "site-a", StartsAt: now, EndsAt: now, Reason: "work"},
		{SiteID: "site-a", StartsAt: now, EndsAt: now.Add(32 * 24 * time.Hour), Reason: "work"},
		{SiteID: "site-a", StartsAt: now, EndsAt: now.Add(time.Hour), Reason: ""},
	}
	for _, input := range tests {
		if _, err := ValidateCreate(input); !errors.Is(err, ErrInvalid) {
			t.Fatalf("ValidateCreate(%+v) error = %v, want ErrInvalid", input, err)
		}
	}
}

func TestValidateListAndEnd(t *testing.T) {
	filter, err := ValidateList(ListFilter{SiteID: "site-a"})
	if err != nil || filter.State != "all" || filter.Limit != 50 {
		t.Fatalf("ValidateList() = %+v, %v", filter, err)
	}
	for _, filter := range []ListFilter{
		{SiteID: "bad_site"},
		{SiteID: "site-a", State: "unknown"},
		{SiteID: "site-a", Limit: 201},
	} {
		if _, err := ValidateList(filter); !errors.Is(err, ErrInvalid) {
			t.Fatalf("ValidateList(%+v) error = %v", filter, err)
		}
	}
	if err := ValidateEnd(EndInput{}); !errors.Is(err, ErrInvalid) {
		t.Fatalf("ValidateEnd() error = %v", err)
	}
}

func TestRoleAndUUIDRules(t *testing.T) {
	for _, role := range []string{"operator", "analyst", "admin", "ot-operator"} {
		if !CanMutate(role) {
			t.Fatalf("CanMutate(%q) = false", role)
		}
	}
	if CanMutate("viewer") {
		t.Fatal("viewer may mutate maintenance")
	}
	id, err := newUUID()
	if err != nil || !validUUID(id) {
		t.Fatalf("newUUID() = %q, %v", id, err)
	}
	for _, invalid := range []string{"", "not-a-uuid", "A682BCEA-B46D-4C7F-91E5-A5760D4E5EF8"} {
		if validUUID(invalid) {
			t.Fatalf("validUUID(%q) = true", invalid)
		}
	}
}
