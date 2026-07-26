package enrollment

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeEnroller struct {
	request  Request
	response Response
	err      error
}

func (f *fakeEnroller) Enroll(_ context.Context, request Request) (Response, error) {
	f.request = request
	return f.response, f.err
}

func TestHandlerEnrollsWithBearerToken(t *testing.T) {
	service := &fakeEnroller{response: Response{
		CertificatePEM:   "leaf",
		CACertificatePEM: "ca",
	}}
	handler := NewHandler(service)
	request := httptest.NewRequest(
		http.MethodPost,
		"/api/pki/enroll",
		strings.NewReader(`{"site_id":"site-a","collector_id":"node-1","csr_pem":"csr"}`),
	)
	request.Header.Set("Authorization", "Bearer secret")
	recorder := httptest.NewRecorder()

	handler.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body=%s", recorder.Code, http.StatusOK, recorder.Body)
	}
	if service.request.Token != "secret" ||
		service.request.SiteID != "site-a" ||
		service.request.CollectorID != "node-1" {
		t.Fatalf("service request = %#v", service.request)
	}
	if got := recorder.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("Cache-Control = %q, want no-store", got)
	}
}

func TestHandlerMapsSafeErrors(t *testing.T) {
	tests := []struct {
		name       string
		serviceErr error
		auth       string
		body       string
		wantStatus int
	}{
		{
			name:       "missing token",
			body:       `{}`,
			wantStatus: http.StatusUnauthorized,
		},
		{
			name:       "rejected token",
			auth:       "Bearer secret",
			body:       `{}`,
			serviceErr: ErrRejected,
			wantStatus: http.StatusUnauthorized,
		},
		{
			name:       "invalid CSR",
			auth:       "Bearer secret",
			body:       `{}`,
			serviceErr: ErrInvalidRequest,
			wantStatus: http.StatusUnprocessableEntity,
		},
		{
			name:       "internal detail hidden",
			auth:       "Bearer secret",
			body:       `{}`,
			serviceErr: errors.New("database password leaked"),
			wantStatus: http.StatusServiceUnavailable,
		},
		{
			name:       "unknown field",
			auth:       "Bearer secret",
			body:       `{"unexpected":true}`,
			wantStatus: http.StatusBadRequest,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			service := &fakeEnroller{err: test.serviceErr}
			request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(test.body))
			request.Header.Set("Authorization", test.auth)
			recorder := httptest.NewRecorder()
			NewHandler(service).ServeHTTP(recorder, request)
			if recorder.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d", recorder.Code, test.wantStatus)
			}
			if strings.Contains(recorder.Body.String(), "password") {
				t.Fatalf("response leaked internal error: %s", recorder.Body)
			}
		})
	}
}

func TestBearerTokenRejectsAmbiguousValues(t *testing.T) {
	for _, value := range []string{"", "Basic token", "Bearer", "Bearer ", "Bearer a b", "Bearer a,b"} {
		if _, ok := bearerToken(value); ok {
			t.Fatalf("bearerToken(%q) accepted invalid value", value)
		}
	}
}
