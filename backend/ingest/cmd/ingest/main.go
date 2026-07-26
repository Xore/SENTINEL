package main

import (
	"context"
	"crypto/tls"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/config"
	"github.com/Xore/analyseLaptop/backend/ingest/internal/enrollment"
	"github.com/Xore/analyseLaptop/backend/ingest/internal/ingest"
	"github.com/Xore/analyseLaptop/backend/ingest/internal/registry"
	"github.com/Xore/analyseLaptop/backend/ingest/internal/sink"
	"github.com/Xore/analyseLaptop/backend/ingest/internal/transport"
	collectormetricspb "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
)

func main() {
	if err := run(); err != nil {
		slog.Error("ingest stopped", "error", err)
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	tlsConfig, err := transport.ServerTLSConfig(
		cfg.TLSCertFile,
		cfg.TLSKeyFile,
		cfg.ClientCAFile,
	)
	if err != nil {
		return err
	}
	publicTLSConfig, err := transport.PublicServerTLSConfig(
		cfg.TLSCertFile,
		cfg.TLSKeyFile,
	)
	if err != nil {
		return err
	}
	metricSink, err := sink.NewOTLPHTTP(cfg.VMOTLPURL, 10*time.Second)
	if err != nil {
		return err
	}
	startupContext, cancelStartup := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancelStartup()
	collectorRegistry, err := registry.Open(startupContext, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer collectorRegistry.Close()
	enrollmentService, err := enrollment.Open(
		startupContext,
		cfg.DatabaseURL,
		cfg.CollectorCACertFile,
		cfg.CollectorCAKeyFile,
		cfg.CertificateValidity,
	)
	if err != nil {
		return err
	}
	defer enrollmentService.Close()

	metricService, err := ingest.NewService(metricSink, collectorRegistry)
	if err != nil {
		return err
	}

	listener, err := net.Listen("tcp", cfg.GRPCAddress)
	if err != nil {
		return err
	}
	defer listener.Close()

	grpcServer := grpc.NewServer(
		grpc.Creds(credentials.NewTLS(tlsConfig)),
		grpc.MaxRecvMsgSize(cfg.MaxMessageBytes),
	)
	collectormetricspb.RegisterMetricsServiceServer(grpcServer, metricService)

	var ready atomic.Bool
	healthServer := newHTTPServer(
		cfg.HTTPAddress,
		publicTLSConfig,
		&ready,
		enrollment.NewHandler(enrollmentService),
	)
	errorChannel := make(chan error, 2)
	go func() {
		slog.Info("HTTPS health and enrollment server listening", "address", cfg.HTTPAddress)
		errorChannel <- healthServer.ListenAndServeTLS("", "")
	}()
	go func() {
		ready.Store(true)
		slog.Info("OTLP gRPC ingest listening", "address", cfg.GRPCAddress)
		errorChannel <- grpcServer.Serve(listener)
	}()

	signalContext, stop := signal.NotifyContext(
		context.Background(),
		syscall.SIGINT,
		syscall.SIGTERM,
	)
	defer stop()

	select {
	case <-signalContext.Done():
		ready.Store(false)
	case serveErr := <-errorChannel:
		ready.Store(false)
		if !errors.Is(serveErr, http.ErrServerClosed) &&
			!errors.Is(serveErr, grpc.ErrServerStopped) {
			return serveErr
		}
	}

	shutdownContext, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if err := healthServer.Shutdown(shutdownContext); err != nil {
		slog.Warn("health server shutdown failed", "error", err)
	}
	gracefulStop(grpcServer, shutdownContext)
	return nil
}

func newHTTPServer(
	address string,
	tlsConfig *tls.Config,
	ready *atomic.Bool,
	enrollmentHandler http.Handler,
) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(writer http.ResponseWriter, _ *http.Request) {
		writer.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("/readyz", func(writer http.ResponseWriter, _ *http.Request) {
		if !ready.Load() {
			http.Error(writer, "not ready", http.StatusServiceUnavailable)
			return
		}
		writer.WriteHeader(http.StatusNoContent)
	})
	mux.Handle("/api/pki/enroll", enrollmentHandler)
	return &http.Server{
		Addr:              address,
		Handler:           mux,
		TLSConfig:         tlsConfig,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
}

func gracefulStop(server *grpc.Server, ctx context.Context) {
	stopped := make(chan struct{})
	go func() {
		server.GracefulStop()
		close(stopped)
	}()
	select {
	case <-stopped:
	case <-ctx.Done():
		server.Stop()
	}
}
