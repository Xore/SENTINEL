// Package fleetops reads site-scoped fleet operations projections from
// PostgreSQL. It is a query-only foundation: HTTP routing is added separately.
package fleetops

import "time"

// Collector lifecycle states. The first four partition the enabled fleet;
// certificate_expiring is an orthogonal flag, not a state.
const (
	StateActive    = "active"
	StateStale     = "stale"
	StateDisabled  = "disabled"
	StateNeverSeen = "never_seen"
)

// Access identifies the authenticated user and the token's site scope. It
// mirrors the collector registry authorization semantics without importing
// that package: a projection row is visible only when the token scope lists
// the site and the current database state still grants the user access.
type Access struct {
	UserID   string
	Role     string
	SiteIDs  []string
	IssuedAt time.Time
}

// StateCounts holds per-state collector counts. CertificateExpiring counts
// non-disabled collectors whose certificate_not_after is at or before now
// plus the configured expiry window; it overlaps the four lifecycle states.
type StateCounts struct {
	Active              int64 `json:"active"`
	Stale               int64 `json:"stale"`
	Disabled            int64 `json:"disabled"`
	NeverSeen           int64 `json:"never_seen"`
	CertificateExpiring int64 `json:"certificate_expiring"`
}

// SiteSummary is the per-site fleet projection in stable site_id order.
type SiteSummary struct {
	SiteID string `json:"site_id"`
	StateCounts
}

// Summary is the fleet-wide projection. Totals is the exact sum over Sites;
// Sites is empty (never null) when the caller's scope matches no site.
type Summary struct {
	Totals StateCounts   `json:"totals"`
	Sites  []SiteSummary `json:"sites"`
}

// CollectorDetail is the bounded per-collector projection in stable
// (site_id, collector_id) order. Nullable database values stay pointers so
// the JSON shape matches the existing collector status contract.
type CollectorDetail struct {
	SiteID              string     `json:"site_id"`
	CollectorID         string     `json:"collector_id"`
	State               string     `json:"state"`
	LastSeen            *time.Time `json:"last_seen"`
	SilenceSeconds      *int64     `json:"silence_seconds"`
	EnrolledAt          time.Time  `json:"enrolled_at"`
	CertificateNotAfter *time.Time `json:"certificate_not_after"`
	CertExpiresInDays   *int64     `json:"cert_expires_in_days"`
}

// CollectorFilter bounds the collector detail lookup. An empty SiteID lists
// every site in scope; a set SiteID narrows to that site but never widens the
// caller's scope. An empty State lists all states. Limit is clamped to the
// package default and maximum by the store.
type CollectorFilter struct {
	SiteID string
	State  string
	Limit  int
}
