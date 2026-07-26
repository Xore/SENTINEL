// Package config loads and validates ingest process configuration.
package config

import (
	"errors"
	"fmt"
	"os"
	"time"
)

// Config contains the production ingest process settings.
type Config struct {
	GRPCAddress     string
	HTTPAddress     string
	TLSCertFile     string
	TLSKeyFile      string
	ClientCAFile    string
	VMOTLPURL       string
	MaxMessageBytes int
	ShutdownTimeout time.Duration
}

// Load reads configuration from the environment.
func Load() (Config, error) {
	cfg := Config{
		GRPCAddress:  envOr("SENTINEL_INGEST_GRPC_ADDRESS", ":4317"),
		HTTPAddress:  envOr("SENTINEL_INGEST_HTTP_ADDRESS", ":8081"),
		TLSCertFile:  os.Getenv("SENTINEL_INGEST_TLS_CERT_FILE"),
		TLSKeyFile:   os.Getenv("SENTINEL_INGEST_TLS_KEY_FILE"),
		ClientCAFile: os.Getenv("SENTINEL_INGEST_CLIENT_CA_FILE"),
		VMOTLPURL: envOr(
			"SENTINEL_INGEST_VM_OTLP_URL",
			"http://victoriametrics:8428/opentelemetry/v1/metrics",
		),
		MaxMessageBytes: 4 << 20,
		ShutdownTimeout: 15 * time.Second,
	}
	if cfg.TLSCertFile == "" || cfg.TLSKeyFile == "" || cfg.ClientCAFile == "" {
		return Config{}, errors.New(
			"SENTINEL_INGEST_TLS_CERT_FILE, SENTINEL_INGEST_TLS_KEY_FILE, " +
				"and SENTINEL_INGEST_CLIENT_CA_FILE are required",
		)
	}
	if cfg.GRPCAddress == cfg.HTTPAddress {
		return Config{}, fmt.Errorf("gRPC and HTTP addresses must differ: %s", cfg.GRPCAddress)
	}
	return cfg, nil
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
