package config

import "testing"

func TestLoadRequiresTLSFiles(t *testing.T) {
	t.Setenv("SENTINEL_INGEST_TLS_CERT_FILE", "")
	t.Setenv("SENTINEL_INGEST_TLS_KEY_FILE", "")
	t.Setenv("SENTINEL_INGEST_CLIENT_CA_FILE", "")

	if _, err := Load(); err == nil {
		t.Fatal("Load() accepted missing TLS files")
	}
}

func TestLoad(t *testing.T) {
	t.Setenv("SENTINEL_INGEST_TLS_CERT_FILE", "/tls/server.crt")
	t.Setenv("SENTINEL_INGEST_TLS_KEY_FILE", "/tls/server.key")
	t.Setenv("SENTINEL_INGEST_CLIENT_CA_FILE", "/tls/ca.crt")
	t.Setenv("SENTINEL_INGEST_GRPC_ADDRESS", ":14317")
	t.Setenv("SENTINEL_INGEST_HTTP_ADDRESS", ":18081")

	got, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got.GRPCAddress != ":14317" || got.HTTPAddress != ":18081" {
		t.Fatalf("Load() addresses = %q, %q", got.GRPCAddress, got.HTTPAddress)
	}
}
