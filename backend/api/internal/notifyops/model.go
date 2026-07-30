// Package notifyops implements a durable site-scoped notification outbox
// with atomic claim leases, bounded exponential-backoff retry scheduling,
// and append-only attempt history. This package never sends network
// messages; delivery transports are a separate integration.
package notifyops

import (
	"encoding/json"
	"errors"
	"regexp"
	"strings"
	"time"
)

// Delivery channels accepted by the durable contract.
const (
	ChannelWebhook = "webhook"
	ChannelSMTP    = "smtp"
)

// Outbox statuses. StatusPending awaits an attempt; StatusLeased is claimed
// by a worker; StatusDelivered and StatusDead are terminal.
const (
	StatusPending   = "pending"
	StatusLeased    = "leased"
	StatusDelivered = "delivered"
	StatusDead      = "dead"
)

// Attempt outcomes recorded in the append-only attempt history.
const (
	OutcomeSuccess          = "success"
	OutcomeRetryableFailure = "retryable_failure"
	OutcomePermanentFailure = "permanent_failure"
)

const (
	maxDedupKeyLength   = 200
	maxPayloadBytes     = 8192
	maxWorkerIDLength   = 100
	maxDetailLength     = 500
	defaultMaxAttempts  = 8
	maxMaxAttempts      = 32
	defaultClaimLimit   = 50
	maxClaimLimit       = 200
	defaultLeaseSeconds = 60
	maxLeaseSeconds     = 600
)

var (
	siteIDPattern = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

	// ErrInvalid indicates that an operation violates the public contract.
	ErrInvalid = errors.New("invalid notification operation")
	// ErrForbidden indicates that the current role cannot operate the outbox.
	ErrForbidden = errors.New("notification operation forbidden")
	// ErrNotFound intentionally combines missing and unauthorized resources.
	ErrNotFound = errors.New("notification not found")
	// ErrConflict indicates a version or lease-ownership mismatch.
	ErrConflict = errors.New("notification version conflict")
	// ErrUnavailable indicates that the durable authority could not respond.
	ErrUnavailable = errors.New("notification outbox unavailable")
)

// Access is the current authenticated database authorization scope.
type Access struct {
	UserID   string
	Role     string
	SiteIDs  []string
	IssuedAt time.Time
}

// Notification is the stable outbox projection. Payload carries metadata
// only; endpoint credentials and raw secrets are never stored here or in
// LastError.
type Notification struct {
	ID            string          `json:"id"`
	SiteID        string          `json:"site_id"`
	Channel       string          `json:"channel"`
	DedupKey      string          `json:"dedup_key"`
	Payload       json.RawMessage `json:"payload"`
	Status        string          `json:"status"`
	Attempts      int             `json:"attempts"`
	MaxAttempts   int             `json:"max_attempts"`
	NextAttemptAt time.Time       `json:"next_attempt_at"`
	LeasedBy      *string         `json:"leased_by"`
	LeaseExpires  *time.Time      `json:"lease_expires_at"`
	LastError     *string         `json:"last_error"`
	Version       int64           `json:"version"`
	CreatedBy     string          `json:"created_by"`
	CreatedAt     time.Time       `json:"created_at"`
	DeliveredAt   *time.Time      `json:"delivered_at"`
}

// EnqueueInput is the validated idempotent enqueue operation. Repeating an
// enqueue with the same (site_id, channel, dedup_key) returns the existing
// notification unchanged.
type EnqueueInput struct {
	SiteID      string          `json:"site_id"`
	Channel     string          `json:"channel"`
	DedupKey    string          `json:"dedup_key"`
	Payload     json.RawMessage `json:"payload"`
	MaxAttempts int             `json:"max_attempts"`
}

// ClaimInput bounds one atomic lease batch.
type ClaimInput struct {
	WorkerID string
	Limit    int
	Lease    time.Duration
}

// CompleteInput is the optimistic-concurrency delivery outcome report from
// the worker holding the lease.
type CompleteInput struct {
	ExpectedVersion int64
	WorkerID        string
	Outcome         string
	Detail          string
}

// ValidateEnqueue validates and normalizes an enqueue request. The payload
// must be a bounded JSON object; callers must strip secrets before enqueue.
func ValidateEnqueue(input EnqueueInput) (EnqueueInput, error) {
	input.SiteID = strings.TrimSpace(input.SiteID)
	input.Channel = strings.TrimSpace(input.Channel)
	input.DedupKey = strings.TrimSpace(input.DedupKey)
	if input.MaxAttempts == 0 {
		input.MaxAttempts = defaultMaxAttempts
	}
	if !siteIDPattern.MatchString(input.SiteID) ||
		input.DedupKey == "" || len(input.DedupKey) > maxDedupKeyLength ||
		input.MaxAttempts < 1 || input.MaxAttempts > maxMaxAttempts ||
		len(input.Payload) == 0 || len(input.Payload) > maxPayloadBytes {
		return EnqueueInput{}, ErrInvalid
	}
	switch input.Channel {
	case ChannelWebhook, ChannelSMTP:
	default:
		return EnqueueInput{}, ErrInvalid
	}
	var payload map[string]json.RawMessage
	if err := json.Unmarshal(input.Payload, &payload); err != nil || payload == nil {
		return EnqueueInput{}, ErrInvalid
	}
	return input, nil
}

// ValidateClaim validates and normalizes a claim request.
func ValidateClaim(input ClaimInput) (ClaimInput, error) {
	input.WorkerID = strings.TrimSpace(input.WorkerID)
	if input.Limit == 0 {
		input.Limit = defaultClaimLimit
	}
	if input.Lease == 0 {
		input.Lease = defaultLeaseSeconds * time.Second
	}
	if input.WorkerID == "" || len(input.WorkerID) > maxWorkerIDLength ||
		input.Limit < 1 || input.Limit > maxClaimLimit ||
		input.Lease < time.Second || input.Lease > maxLeaseSeconds*time.Second {
		return ClaimInput{}, ErrInvalid
	}
	return input, nil
}

// ValidateComplete validates and normalizes a completion report. Details are
// operator-visible metadata and must never contain credentials or secrets.
func ValidateComplete(input CompleteInput) (CompleteInput, error) {
	input.WorkerID = strings.TrimSpace(input.WorkerID)
	input.Detail = strings.TrimSpace(input.Detail)
	if input.ExpectedVersion < 1 ||
		input.WorkerID == "" || len(input.WorkerID) > maxWorkerIDLength ||
		len(input.Detail) > maxDetailLength {
		return CompleteInput{}, ErrInvalid
	}
	switch input.Outcome {
	case OutcomeSuccess, OutcomeRetryableFailure, OutcomePermanentFailure:
		return input, nil
	default:
		return CompleteInput{}, ErrInvalid
	}
}

// CanOperate reports whether a role may enqueue, claim, or complete
// notifications. It matches the maintenance and alert mutation policy.
func CanOperate(role string) bool {
	switch role {
	case "operator", "analyst", "admin", "ot-operator":
		return true
	default:
		return false
	}
}

// DefaultBackoff returns the deterministic exponential delay before the
// given 1-based attempt: thirty seconds doubled per prior attempt, capped at
// one hour. There is no jitter, keeping scheduling reproducible.
func DefaultBackoff(attempt int) time.Duration {
	delay := 30 * time.Second
	for i := 1; i < attempt && delay < time.Hour; i++ {
		delay *= 2
	}
	if delay > time.Hour {
		delay = time.Hour
	}
	return delay
}
