// Package config loads and validates site API configuration.
package config

import (
	"errors"
	"fmt"
	"os"
	"time"
)

const minimumJWTSecretBytes = 32

// Config contains production site API settings.
type Config struct {
	Address         string
	DatabaseURL     string
	JWTSecret       []byte
	JWTIssuer       string
	JWTAudience     string
	ReadTimeout     time.Duration
	WriteTimeout    time.Duration
	IdleTimeout     time.Duration
	ShutdownTimeout time.Duration
	QueryTimeout    time.Duration
}

// Load reads configuration from environment variables.
func Load() (Config, error) {
	secret := os.Getenv("SENTINEL_API_JWT_SECRET")
	cfg := Config{
		Address:         envOr("SENTINEL_API_ADDRESS", ":8080"),
		DatabaseURL:     os.Getenv("SENTINEL_DATABASE_URL"),
		JWTSecret:       []byte(secret),
		JWTIssuer:       envOr("SENTINEL_API_JWT_ISSUER", "sentinel-site"),
		JWTAudience:     envOr("SENTINEL_API_JWT_AUDIENCE", "sentinel-site-api"),
		ReadTimeout:     10 * time.Second,
		WriteTimeout:    15 * time.Second,
		IdleTimeout:     60 * time.Second,
		ShutdownTimeout: 15 * time.Second,
		QueryTimeout:    5 * time.Second,
	}
	if cfg.DatabaseURL == "" {
		return Config{}, errors.New("SENTINEL_DATABASE_URL is required")
	}
	if len(cfg.JWTSecret) < minimumJWTSecretBytes {
		return Config{}, fmt.Errorf(
			"SENTINEL_API_JWT_SECRET must contain at least %d bytes",
			minimumJWTSecretBytes,
		)
	}
	if cfg.JWTIssuer == "" || cfg.JWTAudience == "" {
		return Config{}, errors.New("JWT issuer and audience must not be empty")
	}
	return cfg, nil
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
