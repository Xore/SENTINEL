package ingest

import (
	"context"
	"crypto/x509"
	"errors"
	"net/url"
	"testing"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	collectormetricspb "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	metricspb "go.opentelemetry.io/proto/otlp/metrics/v1"
	resourcepb "go.opentelemetry.io/proto/otlp/resource/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type recordingSink struct {
	id    identity.Collector
	calls int
	err   error
}

func (sink *recordingSink) WriteMetrics(
	_ context.Context,
	_ *collectormetricspb.ExportMetricsServiceRequest,
	id identity.Collector,
) error {
	sink.id = id
	sink.calls++
	return sink.err
}

func TestExportAcceptsCertificateBoundIdentity(t *testing.T) {
	t.Parallel()
	sink := &recordingSink{}
	service, err := NewService(sink)
	if err != nil {
		t.Fatal(err)
	}

	_, err = service.Export(
		collectorContext(t, "plant-a", "probe-01"),
		request("plant-a", "probe-01", "sentinel-collector"),
	)
	if err != nil {
		t.Fatalf("Export() error = %v", err)
	}
	if sink.calls != 1 || sink.id != (identity.Collector{
		SiteID: "plant-a", CollectorID: "probe-01",
	}) {
		t.Fatalf("sink calls/id = %d/%#v", sink.calls, sink.id)
	}
}

func TestExportRejectsAttributeIdentityMismatch(t *testing.T) {
	t.Parallel()
	service, _ := NewService(&recordingSink{})

	_, err := service.Export(
		collectorContext(t, "plant-a", "probe-01"),
		request("plant-b", "probe-01", "sentinel-collector"),
	)
	if status.Code(err) != codes.InvalidArgument {
		t.Fatalf("Export() code = %v, want InvalidArgument", status.Code(err))
	}
}

func TestExportRejectsMissingCertificate(t *testing.T) {
	t.Parallel()
	service, _ := NewService(&recordingSink{})

	_, err := service.Export(context.Background(), request("plant-a", "probe-01", "sentinel-collector"))
	if status.Code(err) != codes.Unauthenticated {
		t.Fatalf("Export() code = %v, want Unauthenticated", status.Code(err))
	}
}

func TestExportHidesSinkFailure(t *testing.T) {
	t.Parallel()
	service, _ := NewService(&recordingSink{err: errors.New("contains internal details")})

	_, err := service.Export(
		collectorContext(t, "plant-a", "probe-01"),
		request("plant-a", "probe-01", "sentinel-collector"),
	)
	if status.Code(err) != codes.Unavailable {
		t.Fatalf("Export() code = %v, want Unavailable", status.Code(err))
	}
	if status.Convert(err).Message() != "site metric storage unavailable" {
		t.Fatalf("Export() exposed sink details: %v", err)
	}
}

func collectorContext(t *testing.T, siteID, collectorID string) context.Context {
	t.Helper()
	uri, err := url.Parse(
		"spiffe://sentinel.local/sites/" + siteID + "/collectors/" + collectorID,
	)
	if err != nil {
		t.Fatal(err)
	}
	return PeerContextForTest(
		context.Background(),
		&x509.Certificate{URIs: []*url.URL{uri}},
	)
}

func request(siteID, collectorID, serviceName string) *collectormetricspb.ExportMetricsServiceRequest {
	return &collectormetricspb.ExportMetricsServiceRequest{
		ResourceMetrics: []*metricspb.ResourceMetrics{{
			Resource: &resourcepb.Resource{Attributes: []*commonpb.KeyValue{
				stringAttribute(attributeSiteID, siteID),
				stringAttribute(attributeCollectorID, collectorID),
				stringAttribute(attributeServiceName, serviceName),
			}},
		}},
	}
}

func stringAttribute(key, value string) *commonpb.KeyValue {
	return &commonpb.KeyValue{
		Key: key,
		Value: &commonpb.AnyValue{
			Value: &commonpb.AnyValue_StringValue{StringValue: value},
		},
	}
}
