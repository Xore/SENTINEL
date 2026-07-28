package alertops

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Store persists alert instances and their audit records.
type Store struct {
	pool         *pgxpool.Pool
	queryTimeout time.Duration
}

// NewStore constructs an alert operations store.
func NewStore(pool *pgxpool.Pool, queryTimeout time.Duration) *Store {
	return &Store{pool: pool, queryTimeout: queryTimeout}
}

// Raise creates an authorized alert instance and audit record atomically.
// Repeating a raise with the same site and dedup key returns the existing
// instance with created=false and records no additional audit event.
func (s *Store) Raise(
	ctx context.Context, access Access, input RaiseInput,
) (Instance, bool, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return Instance{}, false, ErrUnavailable
	}
	if !CanMutate(access.Role) {
		return Instance{}, false, ErrForbidden
	}
	normalized, err := ValidateRaise(input)
	if err != nil {
		return Instance{}, false, err
	}
	id, err := newUUID()
	if err != nil {
		return Instance{}, false, ErrUnavailable
	}

	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()
	tx, err := s.pool.BeginTx(queryCtx, pgx.TxOptions{})
	if err != nil {
		return Instance{}, false, ErrUnavailable
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()

	row := tx.QueryRow(queryCtx, `
		INSERT INTO alert_instances (
			alert_id, site_id, dedup_key, severity, summary, source,
			fired_at, created_by
		)
		SELECT $1, $2, $3, $4, $5, $6, $7, u.user_id
		FROM users u
		JOIN user_site_access usa ON usa.user_id = u.user_id
		WHERE u.user_id = $8
		  AND u.role = $9
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $10
		  AND usa.site_id = $2
		  AND usa.site_id = ANY($11::text[])
		ON CONFLICT (site_id, dedup_key) DO NOTHING
		RETURNING `+insertColumns,
		id,
		normalized.SiteID,
		normalized.DedupKey,
		normalized.Severity,
		normalized.Summary,
		normalized.Source,
		normalized.FiredAt,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	instance, err := scanInstance(row)
	if errors.Is(err, pgx.ErrNoRows) {
		existing, findErr := findInstance(queryCtx, tx, access, normalized.SiteID, normalized.DedupKey)
		if findErr != nil {
			return Instance{}, false, findErr
		}
		if err := tx.Commit(queryCtx); err != nil {
			return Instance{}, false, ErrUnavailable
		}
		return existing, false, nil
	}
	if err != nil {
		return Instance{}, false, ErrUnavailable
	}
	if err := insertAudit(
		queryCtx, tx, access, normalized.SiteID, "alert.raised", id, 1,
	); err != nil {
		return Instance{}, false, err
	}
	if err := tx.Commit(queryCtx); err != nil {
		return Instance{}, false, ErrUnavailable
	}
	return instance, true, nil
}

// List returns an authorized, deterministically ordered bounded projection.
func (s *Store) List(
	ctx context.Context, access Access, filter ListFilter,
) ([]Instance, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return nil, ErrUnavailable
	}
	normalized, err := ValidateList(filter)
	if err != nil {
		return nil, err
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()

	rows, err := s.pool.Query(queryCtx, `
		SELECT `+instanceColumns+`
		FROM alert_instances a
		JOIN user_site_access usa ON usa.site_id = a.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE u.user_id = $1
		  AND u.role = $2
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $3
		  AND a.site_id = $4
		  AND a.site_id = ANY($5::text[])
		  AND (
			$6 = 'all'
			OR ($6 = 'acknowledged' AND a.acknowledged_at IS NOT NULL)
			OR ($6 = 'silenced' AND a.acknowledged_at IS NULL
				AND a.silenced_until IS NOT NULL AND a.silenced_until > now())
			OR ($6 = 'active' AND a.acknowledged_at IS NULL
				AND (a.silenced_until IS NULL OR a.silenced_until <= now()))
		  )
		  AND ($7 = '' OR a.severity = $7)
		ORDER BY a.fired_at DESC, a.alert_id DESC
		LIMIT $8`,
		access.UserID,
		access.Role,
		access.IssuedAt,
		normalized.SiteID,
		access.SiteIDs,
		normalized.State,
		normalized.Severity,
		normalized.Limit,
	)
	if err != nil {
		return nil, ErrUnavailable
	}
	defer rows.Close()

	instances := make([]Instance, 0)
	for rows.Next() {
		instance, err := scanInstance(rows)
		if err != nil {
			return nil, ErrUnavailable
		}
		instances = append(instances, instance)
	}
	if rows.Err() != nil {
		return nil, ErrUnavailable
	}
	return instances, nil
}

// Acknowledge marks an authorized instance acknowledged at the expected
// version and records the audit event atomically. Acknowledging an already
// acknowledged instance is an idempotent no-op returning the current state,
// so retries of a lost response never surface a version conflict.
func (s *Store) Acknowledge(
	ctx context.Context, access Access, id string, input AcknowledgeInput,
) (Instance, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return Instance{}, ErrUnavailable
	}
	if !CanMutate(access.Role) {
		return Instance{}, ErrForbidden
	}
	if !validUUID(id) || ValidateAcknowledge(input) != nil {
		return Instance{}, ErrInvalid
	}

	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()
	tx, err := s.pool.BeginTx(queryCtx, pgx.TxOptions{})
	if err != nil {
		return Instance{}, ErrUnavailable
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()

	row := tx.QueryRow(queryCtx, `
		UPDATE alert_instances a
		SET acknowledged_at = now(), acknowledged_by = $1, version = version + 1
		FROM user_site_access usa, users u
		WHERE a.alert_id = $2
		  AND a.version = $3
		  AND a.acknowledged_at IS NULL
		  AND usa.site_id = a.site_id
		  AND u.user_id = usa.user_id
		  AND u.user_id = $1
		  AND u.role = $4
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $5
		  AND a.site_id = ANY($6::text[])
		RETURNING `+instanceColumns,
		access.UserID,
		id,
		input.ExpectedVersion,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	instance, err := scanInstance(row)
	if errors.Is(err, pgx.ErrNoRows) {
		current, findErr := s.loadAuthorized(queryCtx, tx, access, id)
		if findErr != nil {
			return Instance{}, findErr
		}
		if current.AcknowledgedAt != nil {
			if err := tx.Commit(queryCtx); err != nil {
				return Instance{}, ErrUnavailable
			}
			return current, nil
		}
		if current.Version != input.ExpectedVersion {
			return Instance{}, ErrConflict
		}
		return Instance{}, ErrUnavailable
	}
	if err != nil {
		return Instance{}, ErrUnavailable
	}
	if err := insertAudit(
		queryCtx, tx, access, instance.SiteID, "alert.acknowledged", id, instance.Version,
	); err != nil {
		return Instance{}, err
	}
	if err := tx.Commit(queryCtx); err != nil {
		return Instance{}, ErrUnavailable
	}
	return instance, nil
}

// Silence sets a time-bound silence on an authorized instance at the expected
// version and records the audit event atomically. Repeating the same silence
// (until and reason) is an idempotent no-op returning the current state.
func (s *Store) Silence(
	ctx context.Context, access Access, id string, input SilenceInput,
) (Instance, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return Instance{}, ErrUnavailable
	}
	if !CanMutate(access.Role) {
		return Instance{}, ErrForbidden
	}
	normalized, err := ValidateSilence(input, time.Now())
	if !validUUID(id) || err != nil {
		return Instance{}, ErrInvalid
	}

	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()
	tx, err := s.pool.BeginTx(queryCtx, pgx.TxOptions{})
	if err != nil {
		return Instance{}, ErrUnavailable
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()

	row := tx.QueryRow(queryCtx, `
		UPDATE alert_instances a
		SET silenced_until = $2, silenced_by = $1, silence_reason = $3,
			version = version + 1
		FROM user_site_access usa, users u
		WHERE a.alert_id = $4
		  AND a.version = $5
		  AND (a.silenced_until IS DISTINCT FROM $2
			OR a.silence_reason IS DISTINCT FROM $3)
		  AND usa.site_id = a.site_id
		  AND u.user_id = usa.user_id
		  AND u.user_id = $1
		  AND u.role = $6
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $7
		  AND a.site_id = ANY($8::text[])
		RETURNING `+instanceColumns,
		access.UserID,
		normalized.Until,
		normalized.Reason,
		id,
		normalized.ExpectedVersion,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	instance, err := scanInstance(row)
	if errors.Is(err, pgx.ErrNoRows) {
		current, findErr := s.loadAuthorized(queryCtx, tx, access, id)
		if findErr != nil {
			return Instance{}, findErr
		}
		if current.SilencedUntil != nil && current.SilencedUntil.Equal(normalized.Until) &&
			current.SilenceReason != nil && *current.SilenceReason == normalized.Reason {
			if err := tx.Commit(queryCtx); err != nil {
				return Instance{}, ErrUnavailable
			}
			return current, nil
		}
		if current.Version != normalized.ExpectedVersion {
			return Instance{}, ErrConflict
		}
		return Instance{}, ErrUnavailable
	}
	if err != nil {
		return Instance{}, ErrUnavailable
	}
	if err := insertAudit(
		queryCtx, tx, access, instance.SiteID, "alert.silenced", id, instance.Version,
	); err != nil {
		return Instance{}, err
	}
	if err := tx.Commit(queryCtx); err != nil {
		return Instance{}, ErrUnavailable
	}
	return instance, nil
}

// loadAuthorized loads the current authorized instance after a mutation
// matched no row, so the caller can distinguish non-disclosing not-found from
// an idempotent retry or a version conflict.
func (s *Store) loadAuthorized(
	ctx context.Context,
	tx pgx.Tx,
	access Access,
	id string,
) (Instance, error) {
	row := tx.QueryRow(ctx, `
		SELECT `+instanceColumns+`
		FROM alert_instances a
		JOIN user_site_access usa ON usa.site_id = a.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE a.alert_id = $1
		  AND u.user_id = $2
		  AND u.role = $3
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $4
		  AND a.site_id = ANY($5::text[])`,
		id,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	instance, err := scanInstance(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return Instance{}, ErrNotFound
	}
	if err != nil {
		return Instance{}, ErrUnavailable
	}
	return instance, nil
}

func findInstance(
	ctx context.Context,
	tx pgx.Tx,
	access Access,
	siteID string,
	dedupKey string,
) (Instance, error) {
	row := tx.QueryRow(ctx, `
		SELECT `+instanceColumns+`
		FROM alert_instances a
		JOIN user_site_access usa ON usa.site_id = a.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE a.site_id = $1
		  AND a.dedup_key = $2
		  AND u.user_id = $3
		  AND u.role = $4
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $5
		  AND a.site_id = ANY($6::text[])`,
		siteID,
		dedupKey,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	instance, err := scanInstance(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return Instance{}, ErrNotFound
	}
	if err != nil {
		return Instance{}, ErrUnavailable
	}
	return instance, nil
}

func insertAudit(
	ctx context.Context,
	tx pgx.Tx,
	access Access,
	siteID string,
	action string,
	resourceID string,
	resourceVersion int64,
) error {
	auditID, err := newUUID()
	if err != nil {
		return ErrUnavailable
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO operational_audit_log (
			audit_id, site_id, actor_user_id, action,
			resource_type, resource_id, resource_version, details
		)
		VALUES ($1, $2, $3, $4, 'alert_instance', $5, $6, '{}'::jsonb)`,
		auditID,
		siteID,
		access.UserID,
		action,
		resourceID,
		resourceVersion,
	); err != nil {
		return ErrUnavailable
	}
	return nil
}

// instanceColumns is the shared SELECT/RETURNING projection; the derived
// state precedence is acknowledged, then silenced, then active.
const instanceColumns = `
	a.alert_id::text, a.site_id, a.dedup_key, a.severity, a.summary, a.source,
	CASE
		WHEN a.acknowledged_at IS NOT NULL THEN 'acknowledged'
		WHEN a.silenced_until IS NOT NULL AND a.silenced_until > now() THEN 'silenced'
		ELSE 'active'
	END,
	a.fired_at, a.version, a.created_by, a.created_at,
	a.acknowledged_at, a.acknowledged_by,
	a.silenced_until, a.silenced_by, a.silence_reason`

// insertColumns is the same projection for INSERT ... RETURNING, where the
// target table cannot carry an alias and column names are unambiguous.
const insertColumns = `
	alert_id::text, site_id, dedup_key, severity, summary, source,
	CASE
		WHEN acknowledged_at IS NOT NULL THEN 'acknowledged'
		WHEN silenced_until IS NOT NULL AND silenced_until > now() THEN 'silenced'
		ELSE 'active'
	END,
	fired_at, version, created_by, created_at,
	acknowledged_at, acknowledged_by,
	silenced_until, silenced_by, silence_reason`

type scanner interface {
	Scan(...any) error
}

func scanInstance(row scanner) (Instance, error) {
	var instance Instance
	err := row.Scan(
		&instance.ID,
		&instance.SiteID,
		&instance.DedupKey,
		&instance.Severity,
		&instance.Summary,
		&instance.Source,
		&instance.State,
		&instance.FiredAt,
		&instance.Version,
		&instance.CreatedBy,
		&instance.CreatedAt,
		&instance.AcknowledgedAt,
		&instance.AcknowledgedBy,
		&instance.SilencedUntil,
		&instance.SilencedBy,
		&instance.SilenceReason,
	)
	return instance, err
}

func newUUID() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", fmt.Errorf("generate UUID: %w", err)
	}
	value[6] = (value[6] & 0x0f) | 0x40
	value[8] = (value[8] & 0x3f) | 0x80
	raw := hex.EncodeToString(value[:])
	return raw[0:8] + "-" + raw[8:12] + "-" + raw[12:16] + "-" +
		raw[16:20] + "-" + raw[20:32], nil
}

func validUUID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for index, char := range value {
		if index == 8 || index == 13 || index == 18 || index == 23 {
			if char != '-' {
				return false
			}
			continue
		}
		if !((char >= '0' && char <= '9') || (char >= 'a' && char <= 'f')) {
			return false
		}
	}
	return true
}
