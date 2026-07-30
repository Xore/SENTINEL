package notifyops

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Store is the durable notification outbox. Backoff computes the delay
// before the given 1-based attempt; nil selects DefaultBackoff. Tests
// override it for deterministic scheduling.
type Store struct {
	pool         *pgxpool.Pool
	queryTimeout time.Duration
	Backoff      func(attempt int) time.Duration
}

// NewStore constructs a notification outbox store.
func NewStore(pool *pgxpool.Pool, queryTimeout time.Duration) *Store {
	return &Store{pool: pool, queryTimeout: queryTimeout}
}

func (s *Store) backoff(attempt int) time.Duration {
	if s.Backoff != nil {
		return s.Backoff(attempt)
	}
	return DefaultBackoff(attempt)
}

// Enqueue creates an authorized notification. Repeating an enqueue with the
// same site, channel, and dedup key returns the existing notification with
// created=false, keeping producer retries idempotent.
func (s *Store) Enqueue(
	ctx context.Context, access Access, input EnqueueInput,
) (Notification, bool, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return Notification{}, false, ErrUnavailable
	}
	if !CanOperate(access.Role) {
		return Notification{}, false, ErrForbidden
	}
	normalized, err := ValidateEnqueue(input)
	if err != nil {
		return Notification{}, false, err
	}
	id, err := newUUID()
	if err != nil {
		return Notification{}, false, ErrUnavailable
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()

	row := s.pool.QueryRow(queryCtx, `
		INSERT INTO notification_outbox (
			notification_id, site_id, channel, dedup_key, payload,
			max_attempts, created_by
		)
		SELECT $1, $2, $3, $4, $5::jsonb, $6, u.user_id
		FROM users u
		JOIN user_site_access usa ON usa.user_id = u.user_id
		WHERE u.user_id = $7
		  AND u.role = $8
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $9
		  AND usa.site_id = $2
		  AND usa.site_id = ANY($10::text[])
		ON CONFLICT (site_id, channel, dedup_key) DO NOTHING
		RETURNING `+insertColumns,
		id,
		normalized.SiteID,
		normalized.Channel,
		normalized.DedupKey,
		string(normalized.Payload),
		normalized.MaxAttempts,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	notification, err := scanNotification(row)
	if errors.Is(err, pgx.ErrNoRows) {
		existing, findErr := s.findByDedupKey(queryCtx, access, normalized)
		if findErr != nil {
			return Notification{}, false, findErr
		}
		return existing, false, nil
	}
	if err != nil {
		return Notification{}, false, ErrUnavailable
	}
	return notification, true, nil
}

// Claim atomically leases up to input.Limit due notifications in
// deterministic (next_attempt_at, notification_id) order. Rows with an
// expired lease are recoverable here, so a crashed worker never strands a
// notification. Concurrent workers never receive the same row.
func (s *Store) Claim(
	ctx context.Context, access Access, input ClaimInput,
) ([]Notification, error) {
	claimed := make([]Notification, 0)
	if s.pool == nil || s.queryTimeout <= 0 {
		return claimed, ErrUnavailable
	}
	if !CanOperate(access.Role) {
		return claimed, ErrForbidden
	}
	normalized, err := ValidateClaim(input)
	if err != nil {
		return claimed, err
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()

	rows, err := s.pool.Query(queryCtx, `
		WITH claimable AS (
			SELECT n.notification_id
			FROM notification_outbox n
			JOIN user_site_access usa ON usa.site_id = n.site_id
			JOIN users u ON u.user_id = usa.user_id
			WHERE u.user_id = $1
			  AND u.role = $2
			  AND u.disabled_at IS NULL
			  AND u.token_not_before <= $3
			  AND n.site_id = ANY($4::text[])
			  AND (
				(n.status = 'pending' AND n.next_attempt_at <= now())
				OR (n.status = 'leased' AND n.lease_expires_at < now())
			  )
			ORDER BY n.next_attempt_at, n.notification_id
			LIMIT $5
			FOR UPDATE OF n SKIP LOCKED
		), updated AS (
			UPDATE notification_outbox n
			SET status = 'leased',
				leased_by = $6,
				lease_expires_at = now() + ($7::bigint * interval '1 second'),
				version = version + 1
			FROM claimable
			WHERE n.notification_id = claimable.notification_id
			RETURNING `+prefixedColumns("n")+`
		)
		SELECT `+prefixedColumns("updated")+`
		FROM updated
		ORDER BY updated.next_attempt_at, updated.notification_id`,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
		normalized.Limit,
		normalized.WorkerID,
		int64(normalized.Lease/time.Second),
	)
	if err != nil {
		return claimed, ErrUnavailable
	}
	defer rows.Close()

	for rows.Next() {
		notification, err := scanNotification(rows)
		if err != nil {
			return claimed, ErrUnavailable
		}
		claimed = append(claimed, notification)
	}
	if rows.Err() != nil {
		return claimed, ErrUnavailable
	}
	return claimed, nil
}

// Complete records the leased worker's delivery outcome atomically with the
// attempt history. Success delivers; a retryable failure reschedules with
// backoff until attempts are exhausted, then dead-letters; a permanent
// failure dead-letters immediately. Reporting on an already terminal
// notification returns its current state unchanged, so worker retries of a
// lost response never conflict; version or lease-owner mismatches return
// ErrConflict.
func (s *Store) Complete(
	ctx context.Context, access Access, id string, input CompleteInput,
) (Notification, error) {
	if s.pool == nil || s.queryTimeout <= 0 {
		return Notification{}, ErrUnavailable
	}
	if !CanOperate(access.Role) {
		return Notification{}, ErrForbidden
	}
	normalized, err := ValidateComplete(input)
	if !validUUID(id) || err != nil {
		return Notification{}, ErrInvalid
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()
	tx, err := s.pool.BeginTx(queryCtx, pgx.TxOptions{})
	if err != nil {
		return Notification{}, ErrUnavailable
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()

	row := tx.QueryRow(queryCtx, `
		SELECT `+notificationColumns+`
		FROM notification_outbox n
		JOIN user_site_access usa ON usa.site_id = n.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE n.notification_id = $1
		  AND u.user_id = $2
		  AND u.role = $3
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $4
		  AND n.site_id = ANY($5::text[])
		FOR UPDATE OF n`,
		id,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	current, err := scanNotification(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return Notification{}, ErrNotFound
	}
	if err != nil {
		return Notification{}, ErrUnavailable
	}
	if current.Status == StatusDelivered || current.Status == StatusDead {
		if err := tx.Commit(queryCtx); err != nil {
			return Notification{}, ErrUnavailable
		}
		return current, nil
	}
	if current.Status != StatusLeased ||
		current.LeasedBy == nil || *current.LeasedBy != normalized.WorkerID ||
		current.Version != normalized.ExpectedVersion {
		return Notification{}, ErrConflict
	}

	attempt := current.Attempts + 1
	var updated Notification
	switch normalized.Outcome {
	case OutcomeSuccess:
		updated, err = completeWith(queryCtx, tx, id, current.Version, `
			SET status = 'delivered', delivered_at = now(), attempts = attempts + 1,
				leased_by = NULL, lease_expires_at = NULL, last_error = NULL,
				version = version + 1`)
	case OutcomePermanentFailure:
		updated, err = completeWith(queryCtx, tx, id, current.Version, `
			SET status = 'dead', attempts = attempts + 1,
				leased_by = NULL, lease_expires_at = NULL, last_error = $3,
				version = version + 1`, nullableDetail(normalized.Detail))
	default:
		if attempt >= current.MaxAttempts {
			updated, err = completeWith(queryCtx, tx, id, current.Version, `
				SET status = 'dead', attempts = attempts + 1,
					leased_by = NULL, lease_expires_at = NULL, last_error = $3,
					version = version + 1`, nullableDetail(normalized.Detail))
		} else {
			updated, err = completeWith(queryCtx, tx, id, current.Version, `
				SET status = 'pending', attempts = attempts + 1,
					next_attempt_at = now() + ($3::bigint * interval '1 second'),
					leased_by = NULL, lease_expires_at = NULL, last_error = $4,
					version = version + 1`,
				int64(s.backoff(attempt)/time.Second), nullableDetail(normalized.Detail))
		}
	}
	if err != nil {
		return Notification{}, err
	}
	if err := insertAttempt(queryCtx, tx, id, attempt, normalized); err != nil {
		return Notification{}, err
	}
	if err := tx.Commit(queryCtx); err != nil {
		return Notification{}, ErrUnavailable
	}
	return updated, nil
}

// ListAttempts returns the append-only attempt history of an authorized
// notification in attempt order.
func (s *Store) ListAttempts(
	ctx context.Context, access Access, id string,
) ([]Attempt, error) {
	attempts := make([]Attempt, 0)
	if s.pool == nil || s.queryTimeout <= 0 {
		return attempts, ErrUnavailable
	}
	if !validUUID(id) {
		return attempts, ErrInvalid
	}
	queryCtx, cancel := context.WithTimeout(ctx, s.queryTimeout)
	defer cancel()

	rows, err := s.pool.Query(queryCtx, `
		SELECT
			na.attempt_id::text, na.notification_id::text, na.attempt_no,
			na.outcome, na.detail, na.attempted_by, na.attempted_at
		FROM notification_attempts na
		JOIN notification_outbox n ON n.notification_id = na.notification_id
		JOIN user_site_access usa ON usa.site_id = n.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE na.notification_id = $1
		  AND u.user_id = $2
		  AND u.role = $3
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $4
		  AND n.site_id = ANY($5::text[])
		ORDER BY na.attempt_no`,
		id,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	if err != nil {
		return attempts, ErrUnavailable
	}
	defer rows.Close()

	for rows.Next() {
		var attempt Attempt
		if err := rows.Scan(
			&attempt.ID,
			&attempt.NotificationID,
			&attempt.Number,
			&attempt.Outcome,
			&attempt.Detail,
			&attempt.AttemptedBy,
			&attempt.AttemptedAt,
		); err != nil {
			return attempts, ErrUnavailable
		}
		attempts = append(attempts, attempt)
	}
	if rows.Err() != nil {
		return attempts, ErrUnavailable
	}
	return attempts, nil
}

// completeWith applies one terminal or rescheduling transition guarded by
// the locked row's expected version. The row is already locked FOR UPDATE,
// so the version guard can only fail after a store-side anomaly.
func completeWith(
	ctx context.Context,
	tx pgx.Tx,
	id string,
	expectedVersion int64,
	setClause string,
	extra ...any,
) (Notification, error) {
	args := append([]any{id, expectedVersion}, extra...)
	row := tx.QueryRow(ctx, `
		UPDATE notification_outbox n
		`+setClause+`
		WHERE n.notification_id = $1 AND n.version = $2
		RETURNING `+notificationColumns, args...)
	notification, err := scanNotification(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return Notification{}, ErrConflict
	}
	if err != nil {
		return Notification{}, ErrUnavailable
	}
	return notification, nil
}

func insertAttempt(
	ctx context.Context,
	tx pgx.Tx,
	notificationID string,
	attempt int,
	input CompleteInput,
) error {
	attemptID, err := newUUID()
	if err != nil {
		return ErrUnavailable
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO notification_attempts (
			attempt_id, notification_id, attempt_no, outcome, detail, attempted_by
		)
		VALUES ($1, $2, $3, $4, $5, $6)`,
		attemptID,
		notificationID,
		attempt,
		input.Outcome,
		input.Detail,
		input.WorkerID,
	); err != nil {
		return ErrUnavailable
	}
	return nil
}

func (s *Store) findByDedupKey(
	ctx context.Context, access Access, input EnqueueInput,
) (Notification, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT `+notificationColumns+`
		FROM notification_outbox n
		JOIN user_site_access usa ON usa.site_id = n.site_id
		JOIN users u ON u.user_id = usa.user_id
		WHERE n.site_id = $1
		  AND n.channel = $2
		  AND n.dedup_key = $3
		  AND u.user_id = $4
		  AND u.role = $5
		  AND u.disabled_at IS NULL
		  AND u.token_not_before <= $6
		  AND n.site_id = ANY($7::text[])`,
		input.SiteID,
		input.Channel,
		input.DedupKey,
		access.UserID,
		access.Role,
		access.IssuedAt,
		access.SiteIDs,
	)
	notification, err := scanNotification(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return Notification{}, ErrNotFound
	}
	if err != nil {
		return Notification{}, ErrUnavailable
	}
	return notification, nil
}

// nullableDetail stores an empty completion detail as NULL so operator-facing
// error text stays trimmed and bounded.
func nullableDetail(detail string) any {
	if detail == "" {
		return nil
	}
	return detail
}

// Attempt is one append-only delivery attempt record.
type Attempt struct {
	ID             string    `json:"id"`
	NotificationID string    `json:"notification_id"`
	Number         int       `json:"number"`
	Outcome        string    `json:"outcome"`
	Detail         string    `json:"detail"`
	AttemptedBy    string    `json:"attempted_by"`
	AttemptedAt    time.Time `json:"attempted_at"`
}

const columnList = `
	notification_id::text, site_id, channel, dedup_key, payload, status,
	attempts, max_attempts, next_attempt_at, leased_by, lease_expires_at,
	last_error, version, created_by, created_at, delivered_at`

// notificationColumns is the shared SELECT/RETURNING projection.
const notificationColumns = `
	n.notification_id::text, n.site_id, n.channel, n.dedup_key, n.payload, n.status,
	n.attempts, n.max_attempts, n.next_attempt_at, n.leased_by, n.lease_expires_at,
	n.last_error, n.version, n.created_by, n.created_at, n.delivered_at`

// insertColumns is the same projection for INSERT ... RETURNING, where the
// target table cannot carry an alias and column names are unambiguous.
const insertColumns = columnList

// prefixedColumns renders the projection with an explicit table alias.
func prefixedColumns(alias string) string {
	out := "\n"
	fields := []string{
		"notification_id::text", "site_id", "channel", "dedup_key", "payload",
		"status", "attempts", "max_attempts", "next_attempt_at", "leased_by",
		"lease_expires_at", "last_error", "version", "created_by", "created_at",
		"delivered_at",
	}
	for i, field := range fields {
		if i > 0 {
			out += ", "
		}
		out += alias + "." + field
	}
	return out
}

type scanner interface {
	Scan(...any) error
}

func scanNotification(row scanner) (Notification, error) {
	var notification Notification
	var payload []byte
	err := row.Scan(
		&notification.ID,
		&notification.SiteID,
		&notification.Channel,
		&notification.DedupKey,
		&payload,
		&notification.Status,
		&notification.Attempts,
		&notification.MaxAttempts,
		&notification.NextAttemptAt,
		&notification.LeasedBy,
		&notification.LeaseExpires,
		&notification.LastError,
		&notification.Version,
		&notification.CreatedBy,
		&notification.CreatedAt,
		&notification.DeliveredAt,
	)
	notification.Payload = json.RawMessage(payload)
	return notification, err
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
