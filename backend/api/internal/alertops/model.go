// Package alertops implements site-scoped alert instance lifecycle
// operations: durable instances, acknowledgements, and time-bound silences.
package alertops

import (
	"errors"
	"regexp"
	"strings"
	"time"
)

// Lifecycle states. StateActive means neither acknowledged nor currently
// silenced; an expired silence returns the instance to StateActive.
const (
	StateActive       = "active"
	StateAcknowledged = "acknowledged"
	StateSilenced     = "silenced"
)

// Severity levels accepted by the durable contract.
const (
	SeverityInfo     = "info"
	SeverityWarning  = "warning"
	SeverityCritical = "critical"
)

const (
	maxDedupKeyLength      = 200
	maxSummaryLength       = 500
	maxSourceLength        = 100
	maxSilenceReasonLength = 500
	maxSilenceDuration     = 30 * 24 * time.Hour
	defaultListLimit       = 50
	maxListLimit           = 200
)

var (
	siteIDPattern = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

	// ErrInvalid indicates that an operation violates the public contract.
	ErrInvalid = errors.New("invalid alert operation")
	// ErrForbidden indicates that the current role cannot mutate alerts.
	ErrForbidden = errors.New("alert operation forbidden")
	// ErrNotFound intentionally combines missing and unauthorized resources.
	ErrNotFound = errors.New("alert instance not found")
	// ErrConflict indicates an optimistic-concurrency version mismatch.
	ErrConflict = errors.New("alert instance version conflict")
	// ErrUnavailable indicates that the durable authority could not respond.
	ErrUnavailable = errors.New("alert operations store unavailable")
)

// Access is the current authenticated database authorization scope.
type Access struct {
	UserID   string
	Role     string
	SiteIDs  []string
	IssuedAt time.Time
}

// Instance is the stable projection of an alert instance.
type Instance struct {
	ID             string     `json:"id"`
	SiteID         string     `json:"site_id"`
	DedupKey       string     `json:"dedup_key"`
	Severity       string     `json:"severity"`
	Summary        string     `json:"summary"`
	Source         string     `json:"source"`
	State          string     `json:"state"`
	FiredAt        time.Time  `json:"fired_at"`
	Version        int64      `json:"version"`
	CreatedBy      string     `json:"created_by"`
	CreatedAt      time.Time  `json:"created_at"`
	AcknowledgedAt *time.Time `json:"acknowledged_at"`
	AcknowledgedBy *string    `json:"acknowledged_by"`
	SilencedUntil  *time.Time `json:"silenced_until"`
	SilencedBy     *string    `json:"silenced_by"`
	SilenceReason  *string    `json:"silence_reason"`
}

// RaiseInput is the validated idempotent raise operation. Repeating a raise
// with the same (site_id, dedup_key) returns the existing instance.
type RaiseInput struct {
	SiteID   string    `json:"site_id"`
	DedupKey string    `json:"dedup_key"`
	Severity string    `json:"severity"`
	Summary  string    `json:"summary"`
	Source   string    `json:"source"`
	FiredAt  time.Time `json:"fired_at"`
}

// AcknowledgeInput is the optimistic-concurrency acknowledge operation.
type AcknowledgeInput struct {
	ExpectedVersion int64 `json:"expected_version"`
}

// SilenceInput is the optimistic-concurrency time-bound silence operation.
type SilenceInput struct {
	ExpectedVersion int64     `json:"expected_version"`
	Until           time.Time `json:"until"`
	Reason          string    `json:"reason"`
}

// ListFilter bounds a stable site-scoped list operation.
type ListFilter struct {
	SiteID   string
	State    string
	Severity string
	Limit    int
}

// ValidateRaise validates and normalizes a raise request.
func ValidateRaise(input RaiseInput) (RaiseInput, error) {
	input.SiteID = strings.TrimSpace(input.SiteID)
	input.DedupKey = strings.TrimSpace(input.DedupKey)
	input.Severity = strings.TrimSpace(input.Severity)
	input.Summary = strings.TrimSpace(input.Summary)
	input.Source = strings.TrimSpace(input.Source)
	input.FiredAt = input.FiredAt.UTC()
	if !siteIDPattern.MatchString(input.SiteID) ||
		input.DedupKey == "" || len(input.DedupKey) > maxDedupKeyLength ||
		input.Summary == "" || len(input.Summary) > maxSummaryLength ||
		input.Source == "" || len(input.Source) > maxSourceLength ||
		input.FiredAt.IsZero() {
		return RaiseInput{}, ErrInvalid
	}
	switch input.Severity {
	case SeverityInfo, SeverityWarning, SeverityCritical:
		return input, nil
	default:
		return RaiseInput{}, ErrInvalid
	}
}

// ValidateAcknowledge validates an acknowledge request.
func ValidateAcknowledge(input AcknowledgeInput) error {
	if input.ExpectedVersion < 1 {
		return ErrInvalid
	}
	return nil
}

// ValidateSilence validates and normalizes a silence request relative to now:
// the window must start in the future and stay within the bounded duration.
func ValidateSilence(input SilenceInput, now time.Time) (SilenceInput, error) {
	input.Reason = strings.TrimSpace(input.Reason)
	input.Until = input.Until.UTC()
	if input.ExpectedVersion < 1 ||
		input.Reason == "" || len(input.Reason) > maxSilenceReasonLength ||
		input.Until.IsZero() || !input.Until.After(now.UTC()) ||
		input.Until.Sub(now.UTC()) > maxSilenceDuration {
		return SilenceInput{}, ErrInvalid
	}
	return input, nil
}

// ValidateList validates and normalizes a list filter.
func ValidateList(filter ListFilter) (ListFilter, error) {
	filter.SiteID = strings.TrimSpace(filter.SiteID)
	filter.State = strings.TrimSpace(filter.State)
	filter.Severity = strings.TrimSpace(filter.Severity)
	if filter.State == "" {
		filter.State = "all"
	}
	if filter.Limit == 0 {
		filter.Limit = defaultListLimit
	}
	if !siteIDPattern.MatchString(filter.SiteID) ||
		filter.Limit < 1 || filter.Limit > maxListLimit {
		return ListFilter{}, ErrInvalid
	}
	switch filter.State {
	case "all", StateActive, StateAcknowledged, StateSilenced:
	default:
		return ListFilter{}, ErrInvalid
	}
	switch filter.Severity {
	case "", SeverityInfo, SeverityWarning, SeverityCritical:
		return filter, nil
	default:
		return ListFilter{}, ErrInvalid
	}
}

// CanMutate reports whether a role may raise, acknowledge, or silence alerts.
func CanMutate(role string) bool {
	switch role {
	case "operator", "analyst", "admin", "ot-operator":
		return true
	default:
		return false
	}
}
