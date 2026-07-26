// Package ingest implements the authenticated OTLP metrics boundary.
package ingest

import (
	"context"
	"crypto/x509"
	"errors"
	"fmt"
	"time"

	"github.com/Xore/analyseLaptop/backend/ingest/internal/identity"
	collectormetricspb "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/status"
)

const (
	attributeSiteID      = "site_id"
	attributeCollectorID = "collector_id"
	attributeServiceName = "service.name"
)

// MetricsSink accepts an already authenticated and validated request.
type MetricsSink interface {
	WriteMetrics(context.Context, *collectormetricspb.ExportMetricsServiceRequest, identity.Collector) error
}

// CollectorRegistry authorizes a certificate and records authenticated contact.
// The operation must be atomic: an unauthorized/disabled certificate cannot
// update last_seen.
type CollectorRegistry interface {
	AuthorizeAndMarkSeen(context.Context, identity.Collector, time.Time) error
}

// Service is the OTLP MetricsService implementation.
type Service struct {
	collectormetricspb.UnimplementedMetricsServiceServer
	sink     MetricsSink
	registry CollectorRegistry
}

// NewService creates an OTLP metrics service.
func NewService(sink MetricsSink, registry CollectorRegistry) (*Service, error) {
	if sink == nil {
		return nil, errors.New("metrics sink is required")
	}
	if registry == nil {
		return nil, errors.New("collector registry is required")
	}
	return &Service{sink: sink, registry: registry}, nil
}

// Export authenticates certificate identity, validates all resource identities,
// and forwards the request to the configured site-local sink.
func (s *Service) Export(
	ctx context.Context,
	req *collectormetricspb.ExportMetricsServiceRequest,
) (*collectormetricspb.ExportMetricsServiceResponse, error) {
	id, err := identityFromContext(ctx)
	if err != nil {
		return nil, status.Error(codes.Unauthenticated, err.Error())
	}
	if err := validateRequest(req, id); err != nil {
		return nil, status.Error(codes.InvalidArgument, err.Error())
	}
	if err := s.registry.AuthorizeAndMarkSeen(ctx, id, time.Now().UTC()); err != nil {
		if errors.Is(err, ErrCollectorUnauthorized) {
			return nil, status.Error(codes.PermissionDenied, "collector certificate is not authorized")
		}
		return nil, status.Error(codes.Unavailable, "collector registry unavailable")
	}
	if err := s.sink.WriteMetrics(ctx, req, id); err != nil {
		return nil, status.Error(codes.Unavailable, "site metric storage unavailable")
	}
	return &collectormetricspb.ExportMetricsServiceResponse{}, nil
}

// ErrCollectorUnauthorized is returned for unknown, disabled, or
// certificate-mismatched collectors. Details are intentionally collapsed.
var ErrCollectorUnauthorized = errors.New("collector is not authorized")

func identityFromContext(ctx context.Context) (identity.Collector, error) {
	remotePeer, ok := peer.FromContext(ctx)
	if !ok {
		return identity.Collector{}, errors.New("gRPC peer information is missing")
	}
	tlsInfo, ok := remotePeer.AuthInfo.(credentials.TLSInfo)
	if !ok || len(tlsInfo.State.PeerCertificates) == 0 {
		return identity.Collector{}, errors.New("verified client certificate is missing")
	}
	return identity.FromCertificate(tlsInfo.State.PeerCertificates[0])
}

func validateRequest(
	req *collectormetricspb.ExportMetricsServiceRequest,
	id identity.Collector,
) error {
	if req == nil || len(req.ResourceMetrics) == 0 {
		return errors.New("at least one ResourceMetrics message is required")
	}
	for index, resourceMetrics := range req.ResourceMetrics {
		if resourceMetrics == nil || resourceMetrics.Resource == nil {
			return fmt.Errorf("resource_metrics[%d] is missing its resource", index)
		}
		attributes := stringAttributes(resourceMetrics.Resource.Attributes)
		if err := identity.MatchesAttributes(
			id,
			attributes[attributeSiteID],
			attributes[attributeCollectorID],
		); err != nil {
			return fmt.Errorf("resource_metrics[%d]: %w", index, err)
		}
		if attributes[attributeServiceName] != "sentinel-collector" &&
			attributes[attributeServiceName] != "analyselaptop-collector" {
			return fmt.Errorf(
				"resource_metrics[%d]: service.name must identify the SENTINEL collector",
				index,
			)
		}
	}
	return nil
}

func stringAttributes(values []*commonpb.KeyValue) map[string]string {
	result := make(map[string]string, len(values))
	for _, value := range values {
		if value == nil || value.Value == nil {
			continue
		}
		if stringValue, ok := value.Value.Value.(*commonpb.AnyValue_StringValue); ok {
			result[value.Key] = stringValue.StringValue
		}
	}
	return result
}

// PeerContextForTest returns a context containing a TLS client certificate.
// It is exported only to keep authentication tests outside implementation
// internals; production callers receive contexts from gRPC.
func PeerContextForTest(ctx context.Context, cert *x509.Certificate) context.Context {
	return peer.NewContext(ctx, &peer.Peer{
		AuthInfo: credentials.TLSInfo{
			State: structTLSState(cert),
		},
	})
}
