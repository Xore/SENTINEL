// Package sink implements site-local telemetry storage adapters.
package sink

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	collectormetricspb "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"
)

const maxErrorBodyBytes = 4096

// OTLPHTTP forwards protobuf OTLP metrics to the site-local VictoriaMetrics
// OTLP/HTTP endpoint. Identity has already been certificate-validated by ingest.
type OTLPHTTP struct {
	url    string
	client *http.Client
}

// NewOTLPHTTP creates a bounded site-local OTLP/HTTP sink.
func NewOTLPHTTP(url string, timeout time.Duration) (*OTLPHTTP, error) {
	if url == "" {
		return nil, fmt.Errorf("OTLP HTTP URL is required")
	}
	if timeout <= 0 {
		return nil, fmt.Errorf("OTLP HTTP timeout must be positive")
	}
	return &OTLPHTTP{
		url:    url,
		client: &http.Client{Timeout: timeout},
	}, nil
}

// WriteMetrics forwards one already validated OTLP export request.
func (sink *OTLPHTTP) WriteMetrics(
	ctx context.Context,
	request *collectormetricspb.ExportMetricsServiceRequest,
	_ identity.Collector,
) error {
	payload, err := proto.Marshal(request)
	if err != nil {
		return fmt.Errorf("marshal OTLP request: %w", err)
	}
	httpRequest, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		sink.url,
		bytes.NewReader(payload),
	)
	if err != nil {
		return fmt.Errorf("create OTLP request: %w", err)
	}
	httpRequest.Header.Set("Content-Type", "application/x-protobuf")
	httpRequest.Header.Set("User-Agent", "sentinel-ingest")

	response, err := sink.client.Do(httpRequest)
	if err != nil {
		return fmt.Errorf("send OTLP request: %w", err)
	}
	defer response.Body.Close()

	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		body, _ := io.ReadAll(io.LimitReader(response.Body, maxErrorBodyBytes))
		return fmt.Errorf("OTLP endpoint returned %s: %q", response.Status, string(body))
	}
	return nil
}
