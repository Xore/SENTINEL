package transport

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestServerTLSConfigRequiresVerifiedClientsAndTLS13(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	certFile, keyFile, caFile := writeTestCAAndServerCertificate(t, directory)

	config, err := ServerTLSConfig(certFile, keyFile, caFile)
	if err != nil {
		t.Fatalf("ServerTLSConfig() error = %v", err)
	}
	if config.MinVersion != 0x0304 { // tls.VersionTLS13 without mutable defaults.
		t.Fatalf("MinVersion = %#x, want TLS 1.3", config.MinVersion)
	}
	if config.ClientAuth != 4 { // tls.RequireAndVerifyClientCert.
		t.Fatalf("ClientAuth = %v, want RequireAndVerifyClientCert", config.ClientAuth)
	}
}

func TestServerTLSConfigRejectsInvalidCA(t *testing.T) {
	t.Parallel()
	directory := t.TempDir()
	certFile, keyFile, _ := writeTestCAAndServerCertificate(t, directory)
	caFile := filepath.Join(directory, "invalid-ca.pem")
	if err := os.WriteFile(caFile, []byte("not a certificate"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := ServerTLSConfig(certFile, keyFile, caFile); err == nil {
		t.Fatal("ServerTLSConfig() accepted an invalid CA")
	}
}

func writeTestCAAndServerCertificate(t *testing.T, directory string) (string, string, string) {
	t.Helper()
	now := time.Now()
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	caTemplate := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "test collector CA"},
		NotBefore:             now.Add(-time.Minute),
		NotAfter:              now.Add(time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign,
	}
	caDER, err := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	caCert, err := x509.ParseCertificate(caDER)
	if err != nil {
		t.Fatal(err)
	}

	serverKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	serverTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(2),
		Subject:      pkix.Name{CommonName: "ingest"},
		DNSNames:     []string{"ingest"},
		NotBefore:    now.Add(-time.Minute),
		NotAfter:     now.Add(time.Hour),
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		KeyUsage:     x509.KeyUsageDigitalSignature,
	}
	serverDER, err := x509.CreateCertificate(
		rand.Reader,
		serverTemplate,
		caCert,
		&serverKey.PublicKey,
		caKey,
	)
	if err != nil {
		t.Fatal(err)
	}

	caFile := filepath.Join(directory, "ca.pem")
	certFile := filepath.Join(directory, "server.pem")
	keyFile := filepath.Join(directory, "server-key.pem")
	writePEM(t, caFile, "CERTIFICATE", caDER)
	writePEM(t, certFile, "CERTIFICATE", serverDER)
	keyDER, err := x509.MarshalPKCS8PrivateKey(serverKey)
	if err != nil {
		t.Fatal(err)
	}
	writePEM(t, keyFile, "PRIVATE KEY", keyDER)
	return certFile, keyFile, caFile
}

func writePEM(t *testing.T, path, blockType string, bytes []byte) {
	t.Helper()
	file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_EXCL, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	if err := pem.Encode(file, &pem.Block{Type: blockType, Bytes: bytes}); err != nil {
		_ = file.Close()
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
}
