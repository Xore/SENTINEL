package maintenance

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

// Store persists maintenance windows and their audit records.
type Store struct {
	pool         *pgxpool.Pool
	queryTimeout time.Duration
}

// NewStore constructs a maintenance store.
func NewStore(pool *pgxpool.Pool, queryTimeout time.Duration) *Store {
	return &Store{pool: pool, queryTimeout: queryTimeout}
}

// Create creates an authorized maintenance window and audit record atomically.
func (s *Store) Create(
	ctx context.Context, access Access, input CreateInput,
) (Window, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return Window{}, ErrUnavailable
	}
	if !CanMutate(access.Role) {
		return Window{}, ErrForbidden
	}
	normalized, err := ValidateCreate(input)
	if err != nil {
		return Window{}, err
	}
	id, err := newUUID()
	if err != nil {
		return Window{}, ErrUnavailable
	}

	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()
	tx, err := s.pool.BeginTx(queryCtx, pgx.TxOptions{})
	if err != nil {
		return Window{}, ErrUnavailable
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()
	if _, err := tx.Exec(
		queryCtx,
		"SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
		normalized.SiteID,
	); err != nil {
		return Window{}, ErrUnavailable
	}

	window, err := insertWindow(queryCtx, tx, access, normalized, id)
	if err != nil {
		return Window{}, err
	}
	if err := insertAudit(
		queryCtx, tx, access, normalized.SiteID, "maintenance.created", id, 1,
	); err != nil {
		return Window{}, err
	}
	if err := tx.Commit(queryCtx); err != nil {
		return Window{}, ErrUnavailable
	}
	return window, nil
}

func insertWindow(
	ctx context.Context,
	tx pgx.Tx,
	access Access,
	input CreateInput,
	id string,
) (Window, error) {
	row := tx.QueryRow(ctx, `
		INSERT INTO maintenance_windows (
			window_id, site_id, starts_at, ends_at, reason, created_by
		)
		SELECT $1, $2, $3, $4, $5, u.user_id
		FROM users u
		JOIN user_site_access usa ON usa.user_id = u.user_id
		WHERE u.user_id = $6
		  AND u.role = $7
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $8
		  AND usa.site_id = $2
		  AND usa.site_id = ANY($9::text[])
		  AND NOT EXISTS (
			SELECT 1
			FROM maintenance_windows existing
			WHERE existing.site_id = $2
			  AND existing.ended_at IS NULL
			  AND existing.starts_at < $4
			  AND existing.ends_at > $3
		  )
		RETURNING
			window_id::text, site_id, starts_at, ends_at, reason,
			CASE
				WHEN ended_at IS NOT NULL OR ends_at <= now() THEN 'ended'
				WHEN starts_at > now() THEN 'scheduled'
				ELSE 'active'
			END,
			version, created_by, created_at, ended_at, ended_by`,
		id,
		input.SiteID,
		input.StartsAt,
		input.EndsAt,
		input.Reason,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	window, err := scanWindow(row)
	if errors.Is(err, pgx.ErrNoRows) {
		authorized, authErr := authorizedSite(ctx, tx, access, input.SiteID)
		if authErr != nil {
			return Window{}, authErr
		}
		if authorized {
			return Window{}, ErrConflict
		}
		return Window{}, ErrNotFound
	}
	if err != nil {
		return Window{}, ErrUnavailable
	}
	return window, nil
}

// List returns an authorized, deterministically ordered bounded projection.
func (s *Store) List(
	ctx context.Context, access Access, filter ListFilter,
) ([]Window, error) {
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
		SELECT
			mw.window_id::text, mw.site_id, mw.starts_at, mw.ends_at, mw.reason,
			CASE
				WHEN mw.ended_at IS NOT NULL OR mw.ends_at <= now() THEN 'ended'
				WHEN mw.starts_at > now() THEN 'scheduled'
				ELSE 'active'
			END AS state,
			mw.version, mw.created_by, mw.created_at, mw.ended_at, mw.ended_by
		FROM maintenance_windows mw
		JOIN user_site_access usa ON usa.site_id = mw.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE u.user_id = $1
		  AND u.role = $2
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $3
		  AND mw.site_id = $4
		  AND mw.site_id = ANY($5::text[])
		  AND (
			$6 = 'all'
			OR ($6 = 'ended' AND (mw.ended_at IS NOT NULL OR mw.ends_at <= now()))
			OR ($6 = 'scheduled' AND mw.ended_at IS NULL AND mw.starts_at > now())
			OR ($6 = 'active' AND mw.ended_at IS NULL
				AND mw.starts_at <= now() AND mw.ends_at > now())
		  )
		ORDER BY mw.starts_at DESC, mw.window_id DESC
		LIMIT $7`,
		access.UserID,
		access.Role,
		access.IssuedAt,
		normalized.SiteID,
		access.SiteIDs,
		normalized.State,
		normalized.Limit,
	)
	if err != nil {
		return nil, ErrUnavailable
	}
	defer rows.Close()

	windows := make([]Window, 0)
	for rows.Next() {
		window, err := scanWindow(rows)
		if err != nil {
			return nil, ErrUnavailable
		}
		windows = append(windows, window)
	}
	if rows.Err() != nil {
		return nil, ErrUnavailable
	}
	return windows, nil
}

// End explicitly ends an authorized window at the expected version.
func (s *Store) End(
	ctx context.Context, access Access, id string, input EndInput,
) (Window, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return Window{}, ErrUnavailable
	}
	if !CanMutate(access.Role) {
		return Window{}, ErrForbidden
	}
	if !validUUID(id) || ValidateEnd(input) != nil {
		return Window{}, ErrInvalid
	}

	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()
	tx, err := s.pool.BeginTx(queryCtx, pgx.TxOptions{})
	if err != nil {
		return Window{}, ErrUnavailable
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()

	window, err := endWindow(queryCtx, tx, access, id, input.ExpectedVersion)
	if err != nil {
		return Window{}, err
	}
	if err := insertAudit(
		queryCtx, tx, access, window.SiteID, "maintenance.ended", id, window.Version,
	); err != nil {
		return Window{}, err
	}
	if err := tx.Commit(queryCtx); err != nil {
		return Window{}, ErrUnavailable
	}
	return window, nil
}

func endWindow(
	ctx context.Context,
	tx pgx.Tx,
	access Access,
	id string,
	expectedVersion int64,
) (Window, error) {
	row := tx.QueryRow(ctx, `
		UPDATE maintenance_windows mw
		SET ended_at = now(), ended_by = $1, version = version + 1
		FROM user_site_access usa, users u
		WHERE mw.window_id = $2
		  AND mw.version = $3
		  AND mw.ended_at IS NULL
		  AND mw.ends_at > now()
		  AND usa.site_id = mw.site_id
		  AND u.user_id = usa.user_id
		  AND u.user_id = $1
		  AND u.role = $4
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $5
		  AND mw.site_id = ANY($6::text[])
		RETURNING
			mw.window_id::text, mw.site_id, mw.starts_at, mw.ends_at, mw.reason,
			'ended', mw.version, mw.created_by, mw.created_at,
			mw.ended_at, mw.ended_by`,
		access.UserID,
		id,
		expectedVersion,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	window, err := scanWindow(row)
	if err == nil {
		return window, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Window{}, ErrUnavailable
	}

	var currentVersion int64
	var ended bool
	err = tx.QueryRow(ctx, `
		SELECT mw.version, mw.ended_at IS NOT NULL OR mw.ends_at <= now()
		FROM maintenance_windows mw
		JOIN user_site_access usa ON usa.site_id = mw.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE mw.window_id = $1
		  AND u.user_id = $2
		  AND u.role = $3
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $4
		  AND mw.site_id = ANY($5::text[])`,
		id,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	).Scan(&currentVersion, &ended)
	if errors.Is(err, pgx.ErrNoRows) {
		return Window{}, ErrNotFound
	}
	if err != nil {
		return Window{}, ErrUnavailable
	}
	if ended || currentVersion != expectedVersion {
		return Window{}, ErrConflict
	}
	return Window{}, ErrUnavailable
}

func authorizedSite(
	ctx context.Context,
	tx pgx.Tx,
	access Access,
	siteID string,
) (bool, error) {
	var authorized bool
	err := tx.QueryRow(ctx, `
		SELECT EXISTS (
			SELECT 1
			FROM user_site_access usa
			JOIN users u ON u.user_id = usa.user_id
			WHERE u.user_id = $1
			  AND u.role = $2
			  AND u.disabled_at IS NULL
			  AND u.token_not_before <= $3
			  AND usa.site_id = $4
			  AND usa.site_id = ANY($5::text[])
		)`,
		access.UserID,
		access.Role,
		access.IssuedAt,
		siteID,
		access.SiteIDs,
	).Scan(&authorized)
	if err != nil {
		return false, ErrUnavailable
	}
	return authorized, nil
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
		VALUES ($1, $2, $3, $4, 'maintenance_window', $5, $6, '{}'::jsonb)`,
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

type scanner interface {
	Scan(...any) error
}

func scanWindow(row scanner) (Window, error) {
	var window Window
	err := row.Scan(
		&window.ID,
		&window.SiteID,
		&window.StartsAt,
		&window.EndsAt,
		&window.Reason,
		&window.State,
		&window.Version,
		&window.CreatedBy,
		&window.CreatedAt,
		&window.EndedAt,
		&window.EndedBy,
	)
	return window, err
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
