// Package registry implements collector authorization and presence storage.
package registry

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	"github.com/Xore/analyseLaptop/backend/ingest/internal/ingest"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Postgres stores the collector registry in PostgreSQL.
type Postgres struct {
	pool *pgxpool.Pool
}

// Open creates and verifies a bounded PostgreSQL pool.
func Open(ctx context.Context, databaseURL string) (*Postgres, error) {
	if databaseURL == "" {
		return nil, errors.New("database URL is required")
	}
	config, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse database configuration: %w", err)
	}
	config.MaxConns = 10
	config.MinConns = 1
	config.MaxConnLifetime = 30 * time.Minute
	config.MaxConnIdleTime = 5 * time.Minute
	config.HealthCheckPeriod = 30 * time.Second

	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, fmt.Errorf("create database pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("connect to database: %w", err)
	}
	return &Postgres{pool: pool}, nil
}

// Close releases the PostgreSQL pool.
func (registry *Postgres) Close() {
	registry.pool.Close()
}

// AuthorizeAndMarkSeen atomically updates only an enabled collector whose
// currently registered certificate serial matches the mTLS peer certificate.
func (registry *Postgres) AuthorizeAndMarkSeen(
	ctx context.Context,
	id identity.Collector,
	observedAt time.Time,
) error {
	if id.CertificateSerial == "" {
		return ingest.ErrCollectorUnauthorized
	}
	commandTag, err := registry.pool.Exec(ctx, `
		UPDATE collectors
		   SET last_seen = $4
		 WHERE site_id = $1
		   AND collector_id = $2
		   AND certificate_serial = $3
		   AND disabled_at IS NULL
	`, id.SiteID, id.CollectorID, id.CertificateSerial, observedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ingest.ErrCollectorUnauthorized
		}
		return fmt.Errorf("authorize collector: %w", err)
	}
	if commandTag.RowsAffected() != 1 {
		return ingest.ErrCollectorUnauthorized
	}
	return nil
}
