package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Xore/analyseLaptop/backend/api/internal/auth"
	"github.com/Xore/analyseLaptop/backend/api/internal/metricquery"
	"github.com/Xore/analyseLaptop/backend/api/internal/registry"
	"github.com/golang-jwt/jwt/v5"
)

var routerTestSecret = []byte(strings.Repeat("r", 32))

type fakeRegistry struct {
	collectors []registry.Collector
	access     registry.Access
	pingErr    error
	listErr    error
	listCalls  int
	authorized bool
	authErr    error
	authCalls  int
	authSite   string
}

func (f *fakeRegistry) Ping(context.Context) error {
	return f.pingErr
}

func (f *fakeRegistry) ListCollectors(
	_ context.Context, access registry.Access,
) ([]registry.Collector, error) {
	f.listCalls++
	f.access = access
	return f.collectors, f.listErr
}

func (f *fakeRegistry) AuthorizeSite(
	_ context.Context, access registry.Access, siteID string,
) (bool, error) {
	f.authCalls++
	f.access = access
	f.authSite = siteID
	return f.authorized, f.authErr
}

type fakeMetrics struct {
	result metricquery.Result
	err    error
	query  metricquery.Query
	calls  int
}

func (f *fakeMetrics) QueryRange(
	_ context.Context, query metricquery.Query,
) (metricquery.Result, error) {
	f.calls++
	f.query = query
	return f.result, f.err
}

func testValidator(t *testing.T) *auth.Validator {
	t.Helper()
	validator, err := auth.NewValidator(routerTestSecret, "sentinel-test", "site-api")
	if err != nil {
		t.Fatal(err)
	}
	return validator
}

func testToken(t *testing.T, sites []string) string {
	t.Helper()
	now := time.Now()
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub":      "viewer-1",
		"iss":      "sentinel-test",
		"aud":      []string{"site-api"},
		"iat":      now.Unix(),
		"nbf":      now.Add(-time.Minute).Unix(),
		"exp":      now.Add(time.Hour).Unix(),
		"role":     "viewer",
		"site_ids": sites,
	})
	raw, err := token.SignedString(routerTestSecret)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func performRequest(handler http.Handler, method, path, token string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, nil)
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func TestHealthAndReadiness(t *testing.T) {
	store := &fakeRegistry{}
	handler := NewRouter(store, testValidator(t), &fakeMetrics{})

	for _, path := range []string{"/healthz", "/readyz"} {
		response := performRequest(handler, http.MethodGet, path, "")
		if response.Code != http.StatusOK {
			t.Fatalf("%s status = %d, want 200", path, response.Code)
		}
		if response.Header().Get("X-Request-ID") == "" {
			t.Fatalf("%s missing request ID", path)
		}
	}
}

func TestCollectorsRequiresAuthentication(t *testing.T) {
	store := &fakeRegistry{}
	handler := NewRouter(store, testValidator(t), &fakeMetrics{})

	response := performRequest(handler, http.MethodGet, "/api/v1/collectors", "")
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", response.Code)
	}
	if store.listCalls != 0 {
		t.Fatalf("ListCollectors called %d times", store.listCalls)
	}
	if !strings.Contains(response.Body.String(), `"code":"unauthorized"`) {
		t.Fatalf("unexpected body: %s", response.Body.String())
	}
}

func TestCollectorsPassesTokenScopeToRegistry(t *testing.T) {
	lastSeen := time.Now().UTC().Truncate(time.Second)
	store := &fakeRegistry{
		collectors: []registry.Collector{
			{
				SiteID:      "site-a",
				CollectorID: "dev-node-1",
				State:       "active",
				LastSeen:    &lastSeen,
				EnrolledAt:  lastSeen.Add(-time.Hour),
			},
		},
	}
	handler := NewRouter(store, testValidator(t), &fakeMetrics{})

	response := performRequest(
		handler,
		http.MethodGet,
		"/api/v1/collectors",
		testToken(t, []string{"site-a"}),
	)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if store.access.UserID != "viewer-1" || store.access.Role != "viewer" ||
		len(store.access.SiteIDs) != 1 || store.access.SiteIDs[0] != "site-a" {
		t.Fatalf("unexpected access: %+v", store.access)
	}
	var payload struct {
		Data []registry.Collector `json:"data"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if len(payload.Data) != 1 || payload.Data[0].CollectorID != "dev-node-1" {
		t.Fatalf("unexpected payload: %+v", payload)
	}
}

func TestReadinessAndCollectorFailureHideDetails(t *testing.T) {
	store := &fakeRegistry{
		pingErr: registry.ErrUnavailable,
		listErr: registry.ErrUnavailable,
	}
	handler := NewRouter(store, testValidator(t), &fakeMetrics{})

	ready := performRequest(handler, http.MethodGet, "/readyz", "")
	if ready.Code != http.StatusServiceUnavailable {
		t.Fatalf("ready status = %d, want 503", ready.Code)
	}
	collectors := performRequest(
		handler,
		http.MethodGet,
		"/api/v1/collectors",
		testToken(t, []string{"site-a"}),
	)
	if collectors.Code != http.StatusServiceUnavailable {
		t.Fatalf("collectors status = %d, want 503", collectors.Code)
	}
	if strings.Contains(collectors.Body.String(), "registry") {
		t.Fatalf("internal detail leaked: %s", collectors.Body.String())
	}
}

func TestMetricsRangeEnforcesSiteAccessAndPassesBoundedQuery(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	store := &fakeRegistry{authorized: true}
	metrics := &fakeMetrics{result: metricquery.Result{
		ResultType: "matrix",
		Series: []metricquery.Series{{
			Metric: map[string]string{
				"site_id":      "site-a",
				"collector_id": "dev-node-1",
			},
			Values: [][]json.RawMessage{
				{json.RawMessage("1720000000"), json.RawMessage(`"1"`)},
			},
		}},
	}}
	handler := NewRouter(store, testValidator(t), metrics)
	path := "/api/v1/metrics/range?metric=sentinel_collector_heartbeat_total" +
		"&site_id=site-a&collector_id=dev-node-1" +
		"&start=" + now.Add(-time.Minute).Format(time.RFC3339) +
		"&end=" + now.Format(time.RFC3339) + "&step=30"

	response := performRequest(handler, http.MethodGet, path, testToken(t, []string{"site-a"}))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
	}
	if store.authCalls != 1 || store.authSite != "site-a" || metrics.calls != 1 ||
		metrics.query.Metric != "sentinel_collector_heartbeat_total" ||
		metrics.query.CollectorID != "dev-node-1" {
		t.Fatalf("unexpected store/metrics calls: store=%+v metrics=%+v", store, metrics)
	}
	if !strings.Contains(response.Body.String(), `"result_type":"matrix"`) {
		t.Fatalf("unexpected body: %s", response.Body.String())
	}
}

func TestMetricsRangeRejectsInvalidAndUnauthorizedQueriesBeforeVictoriaMetrics(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	validPath := "/api/v1/metrics/range?metric=sentinel_collector_heartbeat_total" +
		"&site_id=site-a&start=" + now.Add(-time.Minute).Format(time.RFC3339) +
		"&end=" + now.Format(time.RFC3339) + "&step=30"
	tests := []struct {
		name       string
		path       string
		authorized bool
		wantStatus int
		wantCode   string
	}{
		{
			name:       "arbitrary MetricsQL",
			path:       strings.Replace(validPath, "sentinel_collector_heartbeat_total", "rate(up%5B5m%5D)", 1),
			authorized: true,
			wantStatus: http.StatusBadRequest,
			wantCode:   "invalid_request",
		},
		{
			name:       "unauthorized site",
			path:       validPath,
			authorized: false,
			wantStatus: http.StatusNotFound,
			wantCode:   "not_found",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			store := &fakeRegistry{authorized: test.authorized}
			metrics := &fakeMetrics{}
			handler := NewRouter(store, testValidator(t), metrics)
			response := performRequest(
				handler, http.MethodGet, test.path, testToken(t, []string{"site-a"}),
			)
			if response.Code != test.wantStatus ||
				!strings.Contains(response.Body.String(), `"code":"`+test.wantCode+`"`) {
				t.Fatalf("status/body = %d %s", response.Code, response.Body.String())
			}
			if metrics.calls != 0 {
				t.Fatalf("VictoriaMetrics called %d times", metrics.calls)
			}
		})
	}
}

func TestMetricsRangeHidesDependencyErrors(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	store := &fakeRegistry{authorized: true}
	metrics := &fakeMetrics{err: metricquery.ErrUnavailable}
	handler := NewRouter(store, testValidator(t), metrics)
	path := "/api/v1/metrics/range?metric=sentinel_collector_heartbeat_total" +
		"&site_id=site-a&start=" + now.Add(-time.Minute).Format(time.RFC3339) +
		"&end=" + now.Format(time.RFC3339) + "&step=30"
	response := performRequest(handler, http.MethodGet, path, testToken(t, []string{"site-a"}))
	if response.Code != http.StatusServiceUnavailable ||
		strings.Contains(response.Body.String(), "metrics query") {
		t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
	}
}
