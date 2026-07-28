// Package maintenance implements site-scoped maintenance-window operations.
package maintenance

import (
	"errors"
	"regexp"
	"strings"
	"time"
)

const (
	maxReasonLength = 500
	maxWindowLength = 31 * 24 * time.Hour
	maxListLimit    = 200
)

var (
	siteIDPattern = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

	// ErrInvalid indicates that an operation violates the public contract.
	ErrInvalid = errors.New("invalid maintenance operation")
	// ErrForbidden indicates that the current role cannot mutate maintenance.
	ErrForbidden = errors.New("maintenance operation forbidden")
	// ErrNotFound intentionally combines missing and unauthorized resources.
	ErrNotFound = errors.New("maintenance window not found")
	// ErrConflict indicates an optimistic-concurrency version mismatch.
	ErrConflict = errors.New("maintenance window version conflict")
	// ErrUnavailable indicates that the durable authority could not respond.
	ErrUnavailable = errors.New("maintenance store unavailable")
)

// Access is the current authenticated database authorization scope.
type Access struct {
	UserID   string
	Role     string
	SiteIDs  []string
	IssuedAt time.Time
}

// Window is the stable API projection of a maintenance window.
type Window struct {
	ID        string     `json:"id"`
	SiteID    string     `json:"site_id"`
	StartsAt  time.Time  `json:"starts_at"`
	EndsAt    time.Time  `json:"ends_at"`
	Reason    string     `json:"reason"`
	State     string     `json:"state"`
	Version   int64      `json:"version"`
	CreatedBy string     `json:"created_by"`
	CreatedAt time.Time  `json:"created_at"`
	EndedAt   *time.Time `json:"ended_at"`
	EndedBy   *string    `json:"ended_by"`
}

// CreateInput is the validated create operation.
type CreateInput struct {
	SiteID   string    `json:"site_id"`
	StartsAt time.Time `json:"starts_at"`
	EndsAt   time.Time `json:"ends_at"`
	Reason   string    `json:"reason"`
}

// EndInput is the optimistic-concurrency end operation.
type EndInput struct {
	ExpectedVersion int64 `json:"expected_version"`
}

// ListFilter bounds a stable list operation.
type ListFilter struct {
	SiteID string
	State  string
	Limit  int
}

// ValidateCreate validates and normalizes a create request.
func ValidateCreate(input CreateInput) (CreateInput, error) {
	input.SiteID = strings.TrimSpace(input.SiteID)
	input.Reason = strings.TrimSpace(input.Reason)
	input.StartsAt = input.StartsAt.UTC()
	input.EndsAt = input.EndsAt.UTC()
	if !siteIDPattern.MatchString(input.SiteID) ||
		input.StartsAt.IsZero() || input.EndsAt.IsZero() ||
		!input.EndsAt.After(input.StartsAt) ||
		input.EndsAt.Sub(input.StartsAt) > maxWindowLength ||
		input.Reason == "" || len(input.Reason) > maxReasonLength {
		return CreateInput{}, ErrInvalid
	}
	return input, nil
}

// ValidateEnd validates an end request.
func ValidateEnd(input EndInput) error {
	if input.ExpectedVersion < 1 {
		return ErrInvalid
	}
	return nil
}

// ValidateList validates and normalizes a list filter.
func ValidateList(filter ListFilter) (ListFilter, error) {
	filter.SiteID = strings.TrimSpace(filter.SiteID)
	filter.State = strings.TrimSpace(filter.State)
	if filter.State == "" {
		filter.State = "all"
	}
	if filter.Limit == 0 {
		filter.Limit = 50
	}
	if !siteIDPattern.MatchString(filter.SiteID) ||
		filter.Limit < 1 || filter.Limit > maxListLimit {
		return ListFilter{}, ErrInvalid
	}
	switch filter.State {
	case "all", "scheduled", "active", "ended":
		return filter, nil
	default:
		return ListFilter{}, ErrInvalid
	}
}

// CanMutate reports whether a role may create or end maintenance.
func CanMutate(role string) bool {
	switch role {
	case "operator", "analyst", "admin", "ot-operator":
		return true
	default:
		return false
	}
}
