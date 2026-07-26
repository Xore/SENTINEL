package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/migrations"
	"github.com/jackc/pgx/v5/pgxpool"
)

func main() {
	if err := run(); err != nil {
		log.Printf("migration failed: %v", err)
		os.Exit(1)
	}
}

func run() error {
	databaseURL := flag.String(
		"database-url",
		os.Getenv("SENTINEL_DATABASE_URL"),
		"PostgreSQL connection URL (defaults to SENTINEL_DATABASE_URL)",
	)
	timeout := flag.Duration("timeout", 2*time.Minute, "overall migration timeout")
	flag.Parse()

	if *databaseURL == "" {
		return errors.New("database URL is required via -database-url or SENTINEL_DATABASE_URL")
	}
	if *timeout <= 0 {
		return errors.New("timeout must be positive")
	}

	signalCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(signalCtx, *timeout)
	defer cancel()

	pool, err := pgxpool.New(ctx, *databaseURL)
	if err != nil {
		return fmt.Errorf("open database pool: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return fmt.Errorf("ping database: %w", err)
	}

	if err := migrations.NewRunner(pool).Run(ctx); err != nil {
		return err
	}
	log.Print("database migrations are current")
	return nil
}
