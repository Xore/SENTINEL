package ingest

import (
	"crypto/tls"
	"crypto/x509"
)

func structTLSState(cert *x509.Certificate) tls.ConnectionState {
	if cert == nil {
		return tls.ConnectionState{}
	}
	return tls.ConnectionState{PeerCertificates: []*x509.Certificate{cert}}
}
