package sink

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	collectormetricspb "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	"google.golang.org/protobuf/proto"
)

func TestOTLPHTTPWriteMetrics(t *testing.T) {
	t.Parallel()
	request := &collectormetricspb.ExportMetricsServiceRequest{}
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, incoming *http.Request) {
		if incoming.Header.Get("Content-Type") != "application/x-protobuf" {
			t.Errorf("Content-Type = %q", incoming.Header.Get("Content-Type"))
		}
		body, err := io.ReadAll(incoming.Body)
		if err != nil {
			t.Error(err)
		}
		decoded := &collectormetricspb.ExportMetricsServiceRequest{}
		if err := proto.Unmarshal(body, decoded); err != nil {
			t.Errorf("invalid protobuf payload: %v", err)
		}
		writer.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	sink, err := NewOTLPHTTP(server.URL, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if err := sink.WriteMetrics(
		context.Background(),
		request,
		identity.Collector{SiteID: "a", CollectorID: "b"},
	); err != nil {
		t.Fatalf("WriteMetrics() error = %v", err)
	}
}

func TestOTLPHTTPRejectsStorageFailure(t *testing.T) {
	t.Parallel()
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		http.Error(writer, "not ready", http.StatusServiceUnavailable)
	}))
	defer server.Close()

	sink, _ := NewOTLPHTTP(server.URL, time.Second)
	if err := sink.WriteMetrics(
		context.Background(),
		&collectormetricspb.ExportMetricsServiceRequest{},
		identity.Collector{},
	); err == nil {
		t.Fatal("WriteMetrics() accepted a storage failure")
	}
}
