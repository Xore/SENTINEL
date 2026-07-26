package identity

import (
	"crypto/x509"
	"math/big"
	"net/url"
	"testing"
)

func TestFromCertificate(t *testing.T) {
	t.Parallel()
	uri, err := url.Parse("spiffe://sentinel.local/sites/plant-a/collectors/probe-01")
	if err != nil {
		t.Fatal(err)
	}

	got, err := FromCertificate(&x509.Certificate{
		URIs:         []*url.URL{uri},
		SerialNumber: big.NewInt(42),
	})
	if err != nil {
		t.Fatalf("FromCertificate() error = %v", err)
	}
	want := (Collector{
		SiteID: "plant-a", CollectorID: "probe-01", CertificateSerial: "42",
	})
	if got != want {
		t.Fatalf("FromCertificate() = %#v, want %#v", got, want)
	}
}

func TestFromCertificateRejectsAmbiguousIdentity(t *testing.T) {
	t.Parallel()
	first, _ := url.Parse("spiffe://sentinel.local/sites/a/collectors/one")
	second, _ := url.Parse("spiffe://sentinel.local/sites/a/collectors/two")

	if _, err := FromCertificate(&x509.Certificate{URIs: []*url.URL{first, second}}); err == nil {
		t.Fatal("FromCertificate() accepted multiple collector identities")
	}
}

func TestFromCertificateRejectsInvalidIdentifier(t *testing.T) {
	t.Parallel()
	uri, _ := url.Parse("spiffe://sentinel.local/sites/Plant_A/collectors/probe")

	if _, err := FromCertificate(&x509.Certificate{URIs: []*url.URL{uri}}); err == nil {
		t.Fatal("FromCertificate() accepted an invalid site identifier")
	}
}

func TestMatchesAttributes(t *testing.T) {
	t.Parallel()
	id := Collector{SiteID: "plant-a", CollectorID: "probe-01"}

	if err := MatchesAttributes(id, "plant-a", "probe-01"); err != nil {
		t.Fatalf("MatchesAttributes() unexpected error = %v", err)
	}
	if err := MatchesAttributes(id, "plant-b", "probe-01"); err == nil {
		t.Fatal("MatchesAttributes() accepted a conflicting site_id")
	}
}
