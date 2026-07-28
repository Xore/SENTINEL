package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/Xore/analyseLaptop/backend/api/internal/auth"
	"github.com/Xore/analyseLaptop/backend/api/internal/config"
	"github.com/Xore/analyseLaptop/backend/api/internal/httpapi"
	"github.com/Xore/analyseLaptop/backend/api/internal/maintenance"
	"github.com/Xore/analyseLaptop/backend/api/internal/metricquery"
	"github.com/Xore/analyseLaptop/backend/api/internal/registry"
	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	if err := run(); err != nil {
		log.Printf("site API stopped: %v", err)
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	poolConfig, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		return errors.New("parse database configuration")
	}
	poolConfig.MaxConns = 20
	poolConfig.MinConns = 1

	pool, err := pgxpool.NewWithConfig(context.Background(), poolConfig)
	if err != nil {
		return errors.New("connect database")
	}
	defer pool.Close()

	store := registry.NewStore(pool, cfg.QueryTimeout)
	if err := store.Ping(context.Background()); err != nil {
		return errors.New("database readiness check failed")
	}
	validator, err := auth.NewValidator(cfg.JWTSecret, cfg.JWTIssuer, cfg.JWTAudience)
	if err != nil {
		return err
	}
	metricsClient, err := metricquery.NewClient(cfg.MetricsQueryURL, cfg.MetricsTimeout)
	if err != nil {
		return err
	}
	maintenanceStore := maintenance.NewStore(pool, cfg.QueryTimeout)

	server := &http.Server{
		Addr:         cfg.Address,
		Handler:      httpapi.NewRouter(store, validator, metricsClient, maintenanceStore),
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
		IdleTimeout:  cfg.IdleTimeout,
	}
	serverErrors := make(chan error, 1)
	go func() {
		log.Printf("site API listening on %s", cfg.Address)
		serverErrors <- server.ListenAndServe()
	}()

	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGTERM)
	defer signal.Stop(signals)

	select {
	case err := <-serverErrors:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
		return nil
	case <-signals:
		shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			return errors.New("graceful shutdown failed")
		}
		return nil
	}
}
