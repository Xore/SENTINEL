//go:build integration

package enrollment

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"math/big"
	"os"
	"testing"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	"github.com/jackc/pgx/v5/pgxpool"
)

func TestServiceConsumesTokenAndIssuesBoundCertificate(t *testing.T) {
	databaseURL := os.Getenv("SENTINEL_TEST_DATABASE_URL")
	if databaseURL == "" {
		t.Skip("SENTINEL_TEST_DATABASE_URL is not set")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		t.Fatalf("pgxpool.New() error = %v", err)
	}
	defer pool.Close()

	const (
		siteID      = "enroll-site"
		collectorID = "probe-01"
		token       = "single-use-secret"
	)
	tokenHash := sha256.Sum256([]byte(token))
	if _, err := pool.Exec(ctx, `
INSERT INTO sites (site_id, display_name)
VALUES ($1, 'Enrollment integration site')
ON CONFLICT (site_id) DO NOTHING`, siteID); err != nil {
		t.Fatalf("seed enrollment site: %v", err)
	}
	if _, err := pool.Exec(ctx, `
INSERT INTO collectors (site_id, collector_id)
VALUES ($1, $2)
ON CONFLICT (site_id, collector_id) DO UPDATE
SET certificate_serial = NULL, certificate_not_after = NULL,
    disabled_at = NULL`, siteID, collectorID); err != nil {
		t.Fatalf("seed enrollment collector: %v", err)
	}
	if _, err := pool.Exec(ctx,
		`DELETE FROM enrollment_tokens WHERE site_id = $1 AND collector_id = $2`,
		siteID, collectorID,
	); err != nil {
		t.Fatalf("remove prior enrollment token: %v", err)
	}
	if _, err := pool.Exec(ctx, `
INSERT INTO enrollment_tokens (token_sha256, site_id, collector_id, expires_at)
VALUES ($3, $1, $2, now() + interval '5 minutes')`,
		siteID, collectorID, tokenHash[:],
	); err != nil {
		t.Fatalf("seed enrollment token: %v", err)
	}

	ca := newTestAuthority(t)
	now := time.Date(2026, 7, 26, 10, 0, 0, 0, time.UTC)
	service := &Service{pool: pool, authority: ca, now: func() time.Time { return now }}
	csrPEM, collectorKey := newTestCSR(t, siteID, collectorID)

	response, err := service.Enroll(ctx, Request{
		Token: token, SiteID: siteID, CollectorID: collectorID, CSRPEM: csrPEM,
	})
	if err != nil {
		t.Fatalf("Enroll() error = %v", err)
	}
	leaf, err := parseCertificate([]byte(response.CertificatePEM))
	if err != nil {
		t.Fatalf("parse issued certificate: %v", err)
	}
	if err := leaf.CheckSignatureFrom(ca.certificate); err != nil {
		t.Fatalf("issued certificate signature: %v", err)
	}
	gotIdentity, err := identity.FromCertificate(leaf)
	if err != nil {
		t.Fatalf("identity.FromCertificate() error = %v", err)
	}
	if gotIdentity.SiteID != siteID || gotIdentity.CollectorID != collectorID {
		t.Fatalf("issued identity = %#v", gotIdentity)
	}
	leafPublic, _ := x509.MarshalPKIXPublicKey(leaf.PublicKey)
	keyPublic, _ := x509.MarshalPKIXPublicKey(collectorKey.Public())
	if string(leafPublic) != string(keyPublic) {
		t.Fatal("issued certificate does not contain CSR public key")
	}

	if _, err := service.Enroll(ctx, Request{
		Token: token, SiteID: siteID, CollectorID: collectorID, CSRPEM: csrPEM,
	}); !errors.Is(err, ErrRejected) {
		t.Fatalf("reused token error = %v, want ErrRejected", err)
	}

	var consumedAt *time.Time
	var serial string
	if err := pool.QueryRow(ctx, `
SELECT token.consumed_at, collector.certificate_serial
FROM enrollment_tokens AS token
JOIN collectors AS collector USING (site_id, collector_id)
WHERE token.token_sha256 = $1`, tokenHash[:]).Scan(&consumedAt, &serial); err != nil {
		t.Fatalf("read enrollment state: %v", err)
	}
	if consumedAt == nil || serial != leaf.SerialNumber.String() {
		t.Fatalf("persisted consumed_at=%v serial=%q", consumedAt, serial)
	}
}

func newTestAuthority(t *testing.T) *authority {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate CA key: %v", err)
	}
	now := time.Date(2026, 7, 26, 9, 0, 0, 0, time.UTC)
	template := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "SENTINEL test CA"},
		NotBefore:             now,
		NotAfter:              now.Add(365 * 24 * time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, key.Public(), key)
	if err != nil {
		t.Fatalf("create CA: %v", err)
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatalf("parse CA: %v", err)
	}
	return &authority{
		certificate:    cert,
		certificatePEM: string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})),
		signer:         key,
		validity:       90 * 24 * time.Hour,
	}
}

func newTestCSR(t *testing.T, siteID, collectorID string) (string, *ecdsa.PrivateKey) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate collector key: %v", err)
	}
	template := &x509.CertificateRequest{Subject: pkix.Name{
		CommonName:         collectorID,
		OrganizationalUnit: []string{siteID},
	}}
	der, err := x509.CreateCertificateRequest(rand.Reader, template, key)
	if err != nil {
		t.Fatalf("create CSR: %v", err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: der})), key
}
