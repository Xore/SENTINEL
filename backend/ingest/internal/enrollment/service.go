// Package enrollment implements one-time-token collector certificate issuance.
package enrollment

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var (
	// ErrRejected deliberately combines unknown, expired, consumed, and
	// disabled credentials to avoid turning enrollment into an oracle.
	ErrRejected       = errors.New("enrollment credentials rejected")
	ErrInvalidRequest = errors.New("invalid enrollment request")
)

// Request is the authenticated collector CSR request.
type Request struct {
	Token       string
	SiteID      string
	CollectorID string
	CSRPEM      string
}

// Response contains the signed leaf and its issuing CA.
type Response struct {
	CertificatePEM   string `json:"certificate_pem"`
	CACertificatePEM string `json:"ca_certificate_pem"`
}

// Service atomically consumes enrollment tokens and registers issued certs.
type Service struct {
	pool      *pgxpool.Pool
	authority *authority
	now       func() time.Time
}

// Open loads the CA and opens the enrollment database pool.
func Open(
	ctx context.Context,
	databaseURL, caCertFile, caKeyFile string,
	validity time.Duration,
) (*Service, error) {
	ca, err := loadAuthority(caCertFile, caKeyFile, validity)
	if err != nil {
		return nil, err
	}
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("open enrollment database: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping enrollment database: %w", err)
	}
	return &Service{pool: pool, authority: ca, now: time.Now}, nil
}

// Close releases database connections.
func (s *Service) Close() {
	if s != nil && s.pool != nil {
		s.pool.Close()
	}
}

// Enroll validates the CSR, consumes the bound token, and issues a leaf cert.
func (s *Service) Enroll(ctx context.Context, request Request) (Response, error) {
	id := identity.Collector{SiteID: request.SiteID, CollectorID: request.CollectorID}
	if err := identity.ValidateIdentifier(id.SiteID); err != nil {
		return Response{}, fmt.Errorf("%w: site_id: %v", ErrInvalidRequest, err)
	}
	if err := identity.ValidateIdentifier(id.CollectorID); err != nil {
		return Response{}, fmt.Errorf("%w: collector_id: %v", ErrInvalidRequest, err)
	}
	if request.Token == "" {
		return Response{}, ErrRejected
	}
	csr, err := parseCSR(request.CSRPEM)
	if err != nil {
		return Response{}, fmt.Errorf("%w: %v", ErrInvalidRequest, err)
	}
	if csr.Subject.CommonName != id.CollectorID ||
		len(csr.Subject.OrganizationalUnit) != 1 ||
		csr.Subject.OrganizationalUnit[0] != id.SiteID {
		return Response{}, fmt.Errorf("%w: CSR subject does not match requested identity", ErrInvalidRequest)
	}

	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return Response{}, fmt.Errorf("begin enrollment transaction: %w", err)
	}
	defer func() {
		_ = tx.Rollback(context.Background())
	}()

	tokenHash := sha256.Sum256([]byte(request.Token))
	var accepted bool
	err = tx.QueryRow(ctx, `
UPDATE enrollment_tokens AS token
SET consumed_at = now()
FROM collectors AS collector
WHERE token.token_sha256 = $1
  AND token.site_id = $2
  AND token.collector_id = $3
  AND token.consumed_at IS NULL
  AND token.expires_at > now()
  AND collector.site_id = token.site_id
  AND collector.collector_id = token.collector_id
  AND collector.disabled_at IS NULL
RETURNING true`,
		tokenHash[:], id.SiteID, id.CollectorID,
	).Scan(&accepted)
	if errors.Is(err, pgx.ErrNoRows) {
		return Response{}, ErrRejected
	}
	if err != nil {
		return Response{}, fmt.Errorf("consume enrollment token: %w", err)
	}
	if !accepted {
		return Response{}, ErrRejected
	}

	now := s.now().UTC()
	certificatePEM, serial, notAfter, err := s.authority.issue(now, id, csr)
	if err != nil {
		return Response{}, err
	}
	tag, err := tx.Exec(ctx, `
UPDATE collectors
SET certificate_serial = $3,
    certificate_not_after = $4,
    enrolled_at = $5
WHERE site_id = $1
  AND collector_id = $2
  AND disabled_at IS NULL`,
		id.SiteID, id.CollectorID, serial, notAfter, now,
	)
	if err != nil {
		return Response{}, fmt.Errorf("register collector certificate: %w", err)
	}
	if tag.RowsAffected() != 1 {
		return Response{}, ErrRejected
	}
	if err := tx.Commit(ctx); err != nil {
		return Response{}, fmt.Errorf("commit enrollment transaction: %w", err)
	}

	return Response{
		CertificatePEM:   certificatePEM,
		CACertificatePEM: s.authority.certificatePEM,
	}, nil
}

func parseCSR(contents string) (*x509.CertificateRequest, error) {
	block, rest := pem.Decode([]byte(strings.TrimSpace(contents)))
	if block == nil || block.Type != "CERTIFICATE REQUEST" ||
		len(bytes.TrimSpace(rest)) != 0 {
		return nil, errors.New("csr_pem must contain exactly one PEM certificate request")
	}
	csr, err := x509.ParseCertificateRequest(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("parse CSR: %w", err)
	}
	if err := csr.CheckSignature(); err != nil {
		return nil, fmt.Errorf("verify CSR signature: %w", err)
	}
	return csr, nil
}
