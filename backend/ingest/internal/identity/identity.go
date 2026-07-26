// Package identity validates the certificate-bound SENTINEL collector identity.
package identity

import (
	"crypto/x509"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"
)

const trustDomain = "sentinel.local"

var identifierPattern = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)

// Collector identifies one collector within one site.
type Collector struct {
	SiteID      string
	CollectorID string
}

// ValidateIdentifier applies ADR 0009's DNS-label-compatible identifier rule.
func ValidateIdentifier(value string) error {
	if !identifierPattern.MatchString(value) {
		return fmt.Errorf("identifier %q must be a lower-case DNS label (1-63 characters)", value)
	}
	return nil
}

// SPIFFEURI returns the canonical certificate URI SAN for a collector.
func SPIFFEURI(id Collector) (*url.URL, error) {
	if err := ValidateIdentifier(id.SiteID); err != nil {
		return nil, fmt.Errorf("site_id: %w", err)
	}
	if err := ValidateIdentifier(id.CollectorID); err != nil {
		return nil, fmt.Errorf("collector_id: %w", err)
	}
	return url.Parse(fmt.Sprintf(
		"spiffe://%s/sites/%s/collectors/%s",
		trustDomain,
		id.SiteID,
		id.CollectorID,
	))
}

// FromCertificate extracts exactly one canonical collector URI SAN.
func FromCertificate(cert *x509.Certificate) (Collector, error) {
	if cert == nil {
		return Collector{}, errors.New("client certificate is required")
	}

	var found []Collector
	for _, uri := range cert.URIs {
		id, ok := parseCollectorURI(uri)
		if ok {
			found = append(found, id)
		}
	}
	if len(found) != 1 {
		return Collector{}, fmt.Errorf(
			"certificate must contain exactly one sentinel collector URI SAN, found %d",
			len(found),
		)
	}
	return found[0], nil
}

func parseCollectorURI(uri *url.URL) (Collector, bool) {
	if uri == nil || uri.Scheme != "spiffe" || uri.Host != trustDomain {
		return Collector{}, false
	}
	parts := strings.Split(strings.Trim(uri.Path, "/"), "/")
	if len(parts) != 4 || parts[0] != "sites" || parts[2] != "collectors" {
		return Collector{}, false
	}
	id := Collector{SiteID: parts[1], CollectorID: parts[3]}
	if ValidateIdentifier(id.SiteID) != nil || ValidateIdentifier(id.CollectorID) != nil {
		return Collector{}, false
	}
	return id, true
}

// MatchesAttributes prevents telemetry resource attributes from overriding the
// identity authenticated by the client certificate.
func MatchesAttributes(id Collector, siteID, collectorID string) error {
	if siteID != id.SiteID || collectorID != id.CollectorID {
		return fmt.Errorf(
			"telemetry identity (%s, %s) does not match certificate identity (%s, %s)",
			siteID,
			collectorID,
			id.SiteID,
			id.CollectorID,
		)
	}
	return nil
}
