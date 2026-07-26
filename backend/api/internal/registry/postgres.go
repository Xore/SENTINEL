// Package registry reads site-scoped collector status from PostgreSQL.
package registry

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ErrUnavailable indicates that the registry could not complete a query.
var ErrUnavailable = errors.New("collector registry unavailable")

// Collector is the API-safe fleet status projection.
type Collector struct {
	SiteID              string     `json:"site_id"`
	CollectorID         string     `json:"collector_id"`
	State               string     `json:"state"`
	LastSeen            *time.Time `json:"last_seen"`
	SilenceSeconds      *int64     `json:"silence_seconds"`
	EnrolledAt          time.Time  `json:"enrolled_at"`
	CertificateNotAfter *time.Time `json:"certificate_not_after"`
	CertExpiresInDays   *int64     `json:"cert_expires_in_days"`
}

// Access identifies the authenticated user and token scope.
type Access struct {
	UserID   string
	Role     string
	SiteIDs  []string
	IssuedAt time.Time
}

// Store is a PostgreSQL collector registry.
type Store struct {
	pool         *pgxpool.Pool
	queryTimeout time.Duration
}

// NewStore returns a registry using pool.
func NewStore(pool *pgxpool.Pool, queryTimeout time.Duration) *Store {
	return &Store{pool: pool, queryTimeout: queryTimeout}
}

// Ping checks database readiness with the configured bound.
func (s *Store) Ping(ctx context.Context) error {
	if s.pool == nil {
		return ErrUnavailable
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()
	if err := s.pool.Ping(queryCtx); err != nil {
		return fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	return nil
}

// ListCollectors returns only collectors permitted by both current database
// access and the JWT's site scope. Comparing role and token_not_before makes
// role changes, user revocation, and token revocation effective immediately.
func (s *Store) ListCollectors(ctx context.Context, access Access) ([]Collector, error) {
	if s.pool == nil {
		return nil, ErrUnavailable
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()

	rows, err := s.pool.Query(queryCtx, `
		SELECT
			c.site_id,
			c.collector_id,
			CASE
				WHEN c.disabled_at IS NOT NULL THEN 'disabled'
				WHEN c.last_seen IS NULL THEN 'never_seen'
				WHEN c.last_seen < now() - interval '5 minutes' THEN 'stale'
				ELSE 'active'
			END,
			c.last_seen,
			CASE WHEN c.last_seen IS NULL THEN NULL
				ELSE floor(extract(epoch FROM now() - c.last_seen))::bigint END,
			c.enrolled_at,
			c.certificate_not_after,
			CASE WHEN c.certificate_not_after IS NULL THEN NULL
				ELSE floor(extract(epoch FROM c.certificate_not_after - now()) / 86400)::bigint
			END
		FROM collectors c
		JOIN user_site_access usa ON usa.site_id = c.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE u.user_id = $1
		  AND u.role = $2
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $3
		  AND c.site_id = ANY($4::text[])
		ORDER BY c.site_id, c.collector_id`,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	if err != nil {
		return nil, fmt.Errorf("%w: query collectors", ErrUnavailable)
	}
	defer rows.Close()

	collectors := make([]Collector, 0)
	for rows.Next() {
		var collector Collector
		if err := rows.Scan(
			&collector.SiteID,
			&collector.CollectorID,
			&collector.State,
			&collector.LastSeen,
			&collector.SilenceSeconds,
			&collector.EnrolledAt,
			&collector.CertificateNotAfter,
			&collector.CertExpiresInDays,
		); err != nil {
			return nil, fmt.Errorf("%w: scan collector", ErrUnavailable)
		}
		collectors = append(collectors, collector)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("%w: iterate collectors", ErrUnavailable)
	}
	return collectors, nil
}
