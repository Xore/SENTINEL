package enrollment

import (
	"bytes"
	"crypto"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"net/url"
	"os"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
)

type authority struct {
	certificate    *x509.Certificate
	certificatePEM string
	signer         crypto.Signer
	validity       time.Duration
}

func loadAuthority(certFile, keyFile string, validity time.Duration) (*authority, error) {
	if validity <= 0 {
		return nil, errors.New("collector certificate validity must be positive")
	}
	certPEM, err := os.ReadFile(certFile)
	if err != nil {
		return nil, fmt.Errorf("read collector CA certificate: %w", err)
	}
	keyPEM, err := os.ReadFile(keyFile)
	if err != nil {
		return nil, fmt.Errorf("read collector CA key: %w", err)
	}
	cert, err := parseCertificate(certPEM)
	if err != nil {
		return nil, fmt.Errorf("parse collector CA certificate: %w", err)
	}
	if !cert.IsCA || cert.KeyUsage&x509.KeyUsageCertSign == 0 {
		return nil, errors.New("collector CA certificate is not authorized to sign certificates")
	}
	signer, err := parseSigner(keyPEM)
	if err != nil {
		return nil, fmt.Errorf("parse collector CA key: %w", err)
	}
	certPublic, err := x509.MarshalPKIXPublicKey(cert.PublicKey)
	if err != nil {
		return nil, fmt.Errorf("marshal collector CA public key: %w", err)
	}
	signerPublic, err := x509.MarshalPKIXPublicKey(signer.Public())
	if err != nil {
		return nil, fmt.Errorf("marshal collector CA signer public key: %w", err)
	}
	if !bytes.Equal(certPublic, signerPublic) {
		return nil, errors.New("collector CA certificate and private key do not match")
	}
	return &authority{
		certificate:    cert,
		certificatePEM: string(certPEM),
		signer:         signer,
		validity:       validity,
	}, nil
}

func (a *authority) issue(
	now time.Time,
	id identity.Collector,
	csr *x509.CertificateRequest,
) (certificatePEM string, serial string, notAfter time.Time, err error) {
	uri, err := identity.SPIFFEURI(id)
	if err != nil {
		return "", "", time.Time{}, err
	}
	serialNumber, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return "", "", time.Time{}, fmt.Errorf("generate certificate serial: %w", err)
	}
	if serialNumber.Sign() == 0 {
		serialNumber.SetInt64(1)
	}
	notAfter = now.Add(a.validity)
	if notAfter.After(a.certificate.NotAfter) {
		notAfter = a.certificate.NotAfter
	}
	if !notAfter.After(now) {
		return "", "", time.Time{}, errors.New("collector CA is expired")
	}

	template := &x509.Certificate{
		SerialNumber:          serialNumber,
		Subject:               csr.Subject,
		NotBefore:             now.Add(-5 * time.Minute),
		NotAfter:              notAfter,
		KeyUsage:              x509.KeyUsageDigitalSignature,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
		URIs:                  []*url.URL{uri},
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(
		rand.Reader,
		template,
		a.certificate,
		csr.PublicKey,
		a.signer,
	)
	if err != nil {
		return "", "", time.Time{}, fmt.Errorf("sign collector certificate: %w", err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})),
		serialNumber.String(), notAfter, nil
}

func parseCertificate(contents []byte) (*x509.Certificate, error) {
	block, rest := pem.Decode(contents)
	if block == nil || block.Type != "CERTIFICATE" || len(bytes.TrimSpace(rest)) != 0 {
		return nil, errors.New("expected exactly one PEM certificate")
	}
	return x509.ParseCertificate(block.Bytes)
}

func parseSigner(contents []byte) (crypto.Signer, error) {
	block, rest := pem.Decode(contents)
	if block == nil || len(bytes.TrimSpace(rest)) != 0 {
		return nil, errors.New("expected exactly one PEM private key")
	}
	var key any
	var err error
	switch block.Type {
	case "PRIVATE KEY":
		key, err = x509.ParsePKCS8PrivateKey(block.Bytes)
	case "EC PRIVATE KEY":
		key, err = x509.ParseECPrivateKey(block.Bytes)
	case "RSA PRIVATE KEY":
		key, err = x509.ParsePKCS1PrivateKey(block.Bytes)
	default:
		return nil, fmt.Errorf("unsupported private key PEM type %q", block.Type)
	}
	if err != nil {
		return nil, err
	}
	signer, ok := key.(crypto.Signer)
	if !ok {
		return nil, errors.New("private key cannot sign certificates")
	}
	return signer, nil
}
