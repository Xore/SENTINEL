package fleetops

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// ErrUnavailable indicates that the projection could not complete a query.
var ErrUnavailable = errors.New("fleet operations projection unavailable")

// ErrInvalidFilter indicates an unsupported collector filter value.
var ErrInvalidFilter = errors.New("invalid collector filter")

const (
	// staleThreshold matches the registry and alerting convention: a
	// collector with no accepted batch for five minutes is stale.
	staleThreshold = 5 * time.Minute
	// certificateExpiringWithin matches the documented operational
	// threshold: a certificate expiring within fourteen days needs renewal.
	certificateExpiringWithin = 14 * 24 * time.Hour

	defaultCollectorLimit = 50
	maxCollectorLimit     = 200
)

// Store is a PostgreSQL fleet operations projection.
type Store struct {
	pool         *pgxpool.Pool
	queryTimeout time.Duration
}

// NewStore returns a fleet operations projection using pool.
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

// Summary returns fleet totals and per-site counts restricted to the sites
// permitted by both current database access and the token's site scope. An
// empty or non-intersecting scope returns an empty summary without error, so
// inaccessible sites are indistinguishable from sites without collectors.
func (s *Store) Summary(ctx context.Context, access Access) (Summary, error) {
	summary := Summary{Sites: make([]SiteSummary, 0)}
	if s.pool == nil {
		return summary, ErrUnavailable
	}
	if len(access.SiteIDs) == 0 {
		return summary, nil
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()

	rows, err := s.pool.Query(queryCtx, `
		SELECT
			c.site_id,
			count(*) FILTER (
				WHERE c.disabled_at IS NULL AND c.last_seen IS NOT NULL
					AND c.last_seen >= now() - ($5::bigint * interval '1 second')),
			count(*) FILTER (
				WHERE c.disabled_at IS NULL AND c.last_seen IS NOT NULL
					AND c.last_seen < now() - ($5::bigint * interval '1 second')),
			count(*) FILTER (WHERE c.disabled_at IS NOT NULL),
			count(*) FILTER (WHERE c.disabled_at IS NULL AND c.last_seen IS NULL),
			count(*) FILTER (
				WHERE c.disabled_at IS NULL AND c.certificate_not_after IS NOT NULL
					AND c.certificate_not_after <= now() + ($6::bigint * interval '1 second'))
		FROM collectors c
		JOIN user_site_access usa ON usa.site_id = c.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE u.user_id = $1
		  AND u.role = $2
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $3
		  AND c.site_id = ANY($4::text[])
		GROUP BY c.site_id
		ORDER BY c.site_id`,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
		int64(staleThreshold/time.Second),
		int64(certificateExpiringWithin/time.Second),
	)
	if err != nil {
		return summary, fmt.Errorf("%w: query fleet summary", ErrUnavailable)
	}
	defer rows.Close()

	for rows.Next() {
		var site SiteSummary
		if err := rows.Scan(
			&site.SiteID,
			&site.Active,
			&site.Stale,
			&site.Disabled,
			&site.NeverSeen,
			&site.CertificateExpiring,
		); err != nil {
			return summary, fmt.Errorf("%w: scan fleet summary", ErrUnavailable)
		}
		summary.Totals.Active += site.Active
		summary.Totals.Stale += site.Stale
		summary.Totals.Disabled += site.Disabled
		summary.Totals.NeverSeen += site.NeverSeen
		summary.Totals.CertificateExpiring += site.CertificateExpiring
		summary.Sites = append(summary.Sites, site)
	}
	if err := rows.Err(); err != nil {
		return summary, fmt.Errorf("%w: iterate fleet summary", ErrUnavailable)
	}
	return summary, nil
}

// ListCollectors returns at most filter.Limit collector details restricted to
// the caller's authorized scope, in stable (site_id, collector_id) order. A
// filter naming an inaccessible site or an empty scope returns an empty list
// without error; an unknown state returns ErrInvalidFilter.
func (s *Store) ListCollectors(
	ctx context.Context, access Access, filter CollectorFilter,
) ([]CollectorDetail, error) {
	collectors := make([]CollectorDetail, 0)
	if s.pool == nil {
		return collectors, ErrUnavailable
	}
	filter, err := normalizeFilter(filter)
	if err != nil {
		return collectors, err
	}
	if len(access.SiteIDs) == 0 {
		return collectors, nil
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()

	query, args := collectorDetailQuery(access, filter)
	rows, err := s.pool.Query(queryCtx, query, args...)
	if err != nil {
		return collectors, fmt.Errorf("%w: query collector details", ErrUnavailable)
	}
	defer rows.Close()

	for rows.Next() {
		var collector CollectorDetail
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
			return collectors, fmt.Errorf("%w: scan collector detail", ErrUnavailable)
		}
		collectors = append(collectors, collector)
	}
	if err := rows.Err(); err != nil {
		return collectors, fmt.Errorf("%w: iterate collector details", ErrUnavailable)
	}
	return collectors, nil
}

// normalizeFilter validates the state and clamps the limit to the package
// bounds; a non-positive limit selects the default.
func normalizeFilter(filter CollectorFilter) (CollectorFilter, error) {
	switch filter.State {
	case "", StateActive, StateStale, StateDisabled, StateNeverSeen:
	default:
		return filter, fmt.Errorf("%w: state %q", ErrInvalidFilter, filter.State)
	}
	switch {
	case filter.Limit <= 0:
		filter.Limit = defaultCollectorLimit
	case filter.Limit > maxCollectorLimit:
		filter.Limit = maxCollectorLimit
	}
	return filter, nil
}

// collectorDetailQuery builds the bounded detail query and its arguments. The
// access arguments keep fixed positions ($1-$6) so optional filters append
// predictably; the state CASE must stay identical to the Summary predicates.
func collectorDetailQuery(access Access, filter CollectorFilter) (string, []any) {
	args := []any{
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
		int64(staleThreshold / time.Second),
		filter.Limit,
	}
	query := `
		SELECT
			c.site_id,
			c.collector_id,
			CASE
				WHEN c.disabled_at IS NOT NULL THEN 'disabled'
				WHEN c.last_seen IS NULL THEN 'never_seen'
				WHEN c.last_seen < now() - ($5::bigint * interval '1 second') THEN 'stale'
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
		  AND c.site_id = ANY($4::text[])`
	if filter.SiteID != "" {
		args = append(args, filter.SiteID)
		query += `
		  AND c.site_id = $` + strconv.Itoa(len(args))
	}
	if filter.State != "" {
		args = append(args, filter.State)
		query += `
		  AND CASE
				WHEN c.disabled_at IS NOT NULL THEN 'disabled'
				WHEN c.last_seen IS NULL THEN 'never_seen'
				WHEN c.last_seen < now() - ($5::bigint * interval '1 second') THEN 'stale'
				ELSE 'active'
			END = $` + strconv.Itoa(len(args))
	}
	query += `
		ORDER BY c.site_id, c.collector_id
		LIMIT $6`
	return query, args
}
