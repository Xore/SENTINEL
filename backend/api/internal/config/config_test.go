package config

import (
	"strings"
	"testing"
)

func TestLoadRequiresDatabaseURL(t *testing.T) {
	t.Setenv("SENTINEL_DATABASE_URL", "")
	t.Setenv("SENTINEL_API_JWT_SECRET", strings.Repeat("x", 32))

	if _, err := Load(); err == nil || !strings.Contains(err.Error(), "DATABASE_URL") {
		t.Fatalf("Load() error = %v, want database URL error", err)
	}
}

func TestLoadRequiresLongJWTSecret(t *testing.T) {
	t.Setenv("SENTINEL_DATABASE_URL", "postgres://example")
	t.Setenv("SENTINEL_API_JWT_SECRET", "short")

	if _, err := Load(); err == nil || !strings.Contains(err.Error(), "at least 32 bytes") {
		t.Fatalf("Load() error = %v, want secret length error", err)
	}
}

func TestLoadUsesSafeDefaults(t *testing.T) {
	t.Setenv("SENTINEL_DATABASE_URL", "postgres://example")
	t.Setenv("SENTINEL_API_JWT_SECRET", strings.Repeat("x", 32))
	t.Setenv("SENTINEL_API_ADDRESS", "")
	t.Setenv("SENTINEL_API_JWT_ISSUER", "")
	t.Setenv("SENTINEL_API_JWT_AUDIENCE", "")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.Address != ":8080" || cfg.JWTIssuer != "sentinel-site" ||
		cfg.JWTAudience != "sentinel-site-api" {
		t.Fatalf("unexpected defaults: %+v", cfg)
	}
	if cfg.ReadTimeout <= 0 || cfg.QueryTimeout <= 0 || cfg.ShutdownTimeout <= 0 {
		t.Fatalf("timeouts must be positive: %+v", cfg)
	}
}
