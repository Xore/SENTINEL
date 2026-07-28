package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/Xore/analyseLaptop/backend/api/internal/alertops"
	"github.com/Xore/analyseLaptop/backend/api/internal/auth"
	"github.com/Xore/analyseLaptop/backend/api/internal/maintenance"
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

type fakeMaintenance struct {
	created     maintenance.Window
	listed      []maintenance.Window
	ended       maintenance.Window
	err         error
	access      maintenance.Access
	createInput maintenance.CreateInput
	listFilter  maintenance.ListFilter
	endInput    maintenance.EndInput
	endID       string
	createCalls int
	listCalls   int
	endCalls    int
}

type fakeAlerts struct {
	listed           []alertops.Instance
	acknowledged     alertops.Instance
	silenced         alertops.Instance
	err              error
	access           alertops.Access
	listFilter       alertops.ListFilter
	acknowledgeInput alertops.AcknowledgeInput
	silenceInput     alertops.SilenceInput
	mutationID       string
	listCalls        int
	acknowledgeCalls int
	silenceCalls     int
}

func (f *fakeAlerts) List(
	_ context.Context, access alertops.Access, filter alertops.ListFilter,
) ([]alertops.Instance, error) {
	f.listCalls++
	f.access = access
	f.listFilter = filter
	return f.listed, f.err
}

func (f *fakeAlerts) Acknowledge(
	_ context.Context,
	access alertops.Access,
	id string,
	input alertops.AcknowledgeInput,
) (alertops.Instance, error) {
	f.acknowledgeCalls++
	f.access = access
	f.mutationID = id
	f.acknowledgeInput = input
	return f.acknowledged, f.err
}

func (f *fakeAlerts) Silence(
	_ context.Context,
	access alertops.Access,
	id string,
	input alertops.SilenceInput,
) (alertops.Instance, error) {
	f.silenceCalls++
	f.access = access
	f.mutationID = id
	f.silenceInput = input
	return f.silenced, f.err
}

func (f *fakeMaintenance) Create(
	_ context.Context, access maintenance.Access, input maintenance.CreateInput,
) (maintenance.Window, error) {
	f.createCalls++
	f.access = access
	f.createInput = input
	return f.created, f.err
}

func (f *fakeMaintenance) List(
	_ context.Context, access maintenance.Access, filter maintenance.ListFilter,
) ([]maintenance.Window, error) {
	f.listCalls++
	f.access = access
	f.listFilter = filter
	return f.listed, f.err
}

func (f *fakeMaintenance) End(
	_ context.Context,
	access maintenance.Access,
	id string,
	input maintenance.EndInput,
) (maintenance.Window, error) {
	f.endCalls++
	f.access = access
	f.endID = id
	f.endInput = input
	return f.ended, f.err
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
	return testRoleToken(t, sites, "viewer")
}

func testRoleToken(t *testing.T, sites []string, role string) string {
	t.Helper()
	now := time.Now()
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub":      "viewer-1",
		"iss":      "sentinel-test",
		"aud":      []string{"site-api"},
		"iat":      now.Unix(),
		"nbf":      now.Add(-time.Minute).Unix(),
		"exp":      now.Add(time.Hour).Unix(),
		"role":     role,
		"site_ids": sites,
	})
	raw, err := token.SignedString(routerTestSecret)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func performRequest(handler http.Handler, method, path, token string) *httptest.ResponseRecorder {
	return performRequestBody(handler, method, path, token, "")
}

func performRequestBody(
	handler http.Handler, method, path, token, body string,
) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func TestHealthAndReadiness(t *testing.T) {
	store := &fakeRegistry{}
	handler := NewRouter(store, testValidator(t), &fakeMetrics{}, nil)

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
	handler := NewRouter(store, testValidator(t), &fakeMetrics{}, nil)

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
	handler := NewRouter(store, testValidator(t), &fakeMetrics{}, nil)

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
	handler := NewRouter(store, testValidator(t), &fakeMetrics{}, nil)

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
	handler := NewRouter(store, testValidator(t), metrics, nil)
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
			handler := NewRouter(store, testValidator(t), metrics, nil)
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
	handler := NewRouter(store, testValidator(t), metrics, nil)
	path := "/api/v1/metrics/range?metric=sentinel_collector_heartbeat_total" +
		"&site_id=site-a&start=" + now.Add(-time.Minute).Format(time.RFC3339) +
		"&end=" + now.Format(time.RFC3339) + "&step=30"
	response := performRequest(handler, http.MethodGet, path, testToken(t, []string{"site-a"}))
	if response.Code != http.StatusServiceUnavailable ||
		strings.Contains(response.Body.String(), "metrics query") {
		t.Fatalf("unexpected response: %d %s", response.Code, response.Body.String())
	}
}

func TestMaintenanceCreateAndEnd(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	id := "a682bcea-b46d-4c7f-91e5-a5760d4e5ef8"
	operations := &fakeMaintenance{
		created: maintenance.Window{
			ID:        id,
			SiteID:    "site-a",
			StartsAt:  now,
			EndsAt:    now.Add(time.Hour),
			Reason:    "planned work",
			State:     "active",
			Version:   1,
			CreatedBy: "viewer-1",
			CreatedAt: now,
		},
		ended: maintenance.Window{
			ID:        id,
			SiteID:    "site-a",
			StartsAt:  now,
			EndsAt:    now.Add(time.Hour),
			Reason:    "planned work",
			State:     "ended",
			Version:   2,
			CreatedBy: "viewer-1",
			CreatedAt: now,
		},
	}
	handler := NewRouter(
		&fakeRegistry{}, testValidator(t), &fakeMetrics{}, operations,
	)
	token := testRoleToken(t, []string{"site-a"}, "operator")
	createBody := `{"site_id":"site-a","starts_at":"` + now.Format(time.RFC3339) +
		`","ends_at":"` + now.Add(time.Hour).Format(time.RFC3339) +
		`","reason":"planned work"}`
	created := performRequestBody(
		handler, http.MethodPost, "/api/v1/maintenance-windows", token, createBody,
	)
	if created.Code != http.StatusCreated ||
		created.Header().Get("Location") != "/api/v1/maintenance-windows/"+id ||
		operations.createCalls != 1 ||
		operations.access.Role != "operator" ||
		operations.createInput.SiteID != "site-a" {
		t.Fatalf("create response/store = %d %s %+v", created.Code, created.Body, operations)
	}

	ended := performRequestBody(
		handler,
		http.MethodPost,
		"/api/v1/maintenance-windows/"+id+"/end",
		token,
		`{"expected_version":1}`,
	)
	if ended.Code != http.StatusOK || operations.endCalls != 1 ||
		operations.endID != id || operations.endInput.ExpectedVersion != 1 {
		t.Fatalf("end response/store = %d %s %+v", ended.Code, ended.Body, operations)
	}
}

func TestMaintenanceListIsBoundedAndViewerReadable(t *testing.T) {
	operations := &fakeMaintenance{listed: []maintenance.Window{}}
	handler := NewRouter(
		&fakeRegistry{}, testValidator(t), &fakeMetrics{}, operations,
	)
	response := performRequest(
		handler,
		http.MethodGet,
		"/api/v1/maintenance-windows?site_id=site-a&state=active&limit=25",
		testToken(t, []string{"site-a"}),
	)
	if response.Code != http.StatusOK || operations.listCalls != 1 ||
		operations.listFilter.SiteID != "site-a" ||
		operations.listFilter.State != "active" ||
		operations.listFilter.Limit != 25 {
		t.Fatalf("list response/store = %d %s %+v", response.Code, response.Body, operations)
	}
}

func TestMaintenanceRejectsViewerMutationAndMalformedInputs(t *testing.T) {
	tests := []struct {
		name   string
		method string
		path   string
		token  string
		body   string
		status int
	}{
		{
			name:   "viewer create",
			method: http.MethodPost,
			path:   "/api/v1/maintenance-windows",
			token:  testToken(t, []string{"site-a"}),
			body:   `{}`,
			status: http.StatusForbidden,
		},
		{
			name:   "unknown JSON field",
			method: http.MethodPost,
			path:   "/api/v1/maintenance-windows",
			token:  testRoleToken(t, []string{"site-a"}, "operator"),
			body:   `{"site_id":"site-a","unknown":true}`,
			status: http.StatusBadRequest,
		},
		{
			name:   "unknown query",
			method: http.MethodGet,
			path:   "/api/v1/maintenance-windows?site_id=site-a&extra=true",
			token:  testToken(t, []string{"site-a"}),
			status: http.StatusBadRequest,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			operations := &fakeMaintenance{}
			handler := NewRouter(
				&fakeRegistry{}, testValidator(t), &fakeMetrics{}, operations,
			)
			response := performRequestBody(
				handler, test.method, test.path, test.token, test.body,
			)
			if response.Code != test.status {
				t.Fatalf("status = %d, body = %s", response.Code, response.Body.String())
			}
			if operations.createCalls+operations.listCalls+operations.endCalls != 0 {
				t.Fatalf("store called for rejected request: %+v", operations)
			}
		})
	}
}

func TestMaintenanceMapsNonDisclosingAndConflictErrors(t *testing.T) {
	tests := []struct {
		err      error
		status   int
		wantCode string
	}{
		{maintenance.ErrNotFound, http.StatusNotFound, "not_found"},
		{maintenance.ErrConflict, http.StatusConflict, "conflict"},
		{maintenance.ErrUnavailable, http.StatusServiceUnavailable, "unavailable"},
	}
	for _, test := range tests {
		operations := &fakeMaintenance{err: test.err}
		handler := NewRouter(
			&fakeRegistry{}, testValidator(t), &fakeMetrics{}, operations,
		)
		response := performRequest(
			handler,
			http.MethodGet,
			"/api/v1/maintenance-windows?site_id=site-a",
			testToken(t, []string{"site-a"}),
		)
		if response.Code != test.status ||
			!strings.Contains(response.Body.String(), `"code":"`+test.wantCode+`"`) {
			t.Fatalf("error %v response = %d %s", test.err, response.Code, response.Body)
		}
	}
}

func TestAlertListIsBoundedAndViewerReadable(t *testing.T) {
	operations := &fakeAlerts{listed: []alertops.Instance{}}
	handler := NewRouter(
		&fakeRegistry{}, testValidator(t), &fakeMetrics{}, nil, operations,
	)
	response := performRequest(
		handler,
		http.MethodGet,
		"/api/v1/alerts?site_id=site-a&state=active&severity=critical&limit=25",
		testToken(t, []string{"site-a"}),
	)
	if response.Code != http.StatusOK || operations.listCalls != 1 ||
		operations.access.Role != "viewer" ||
		operations.listFilter != (alertops.ListFilter{
			SiteID: "site-a", State: "active", Severity: "critical", Limit: 25,
		}) {
		t.Fatalf("list response/store = %d %s %+v", response.Code, response.Body, operations)
	}
}

func TestAlertAcknowledgeAndSilence(t *testing.T) {
	id := "a682bcea-b46d-4c7f-91e5-a5760d4e5ef8"
	operations := &fakeAlerts{
		acknowledged: alertops.Instance{ID: id, State: alertops.StateAcknowledged, Version: 2},
		silenced:     alertops.Instance{ID: id, State: alertops.StateSilenced, Version: 3},
	}
	handler := NewRouter(
		&fakeRegistry{}, testValidator(t), &fakeMetrics{}, nil, operations,
	)
	token := testRoleToken(t, []string{"site-a"}, "operator")
	response := performRequestBody(
		handler, http.MethodPost, "/api/v1/alerts/"+id+"/acknowledge",
		token, `{"expected_version":1}`,
	)
	if response.Code != http.StatusOK || operations.acknowledgeCalls != 1 ||
		operations.mutationID != id || operations.acknowledgeInput.ExpectedVersion != 1 {
		t.Fatalf("acknowledge response/store = %d %s %+v", response.Code, response.Body, operations)
	}

	until := time.Now().Add(time.Hour).UTC().Truncate(time.Second)
	response = performRequestBody(
		handler, http.MethodPost, "/api/v1/alerts/"+id+"/silence", token,
		`{"expected_version":2,"until":"`+until.Format(time.RFC3339)+`","reason":"deploy"}`,
	)
	if response.Code != http.StatusOK || operations.silenceCalls != 1 ||
		operations.silenceInput.ExpectedVersion != 2 ||
		!operations.silenceInput.Until.Equal(until) ||
		operations.silenceInput.Reason != "deploy" {
		t.Fatalf("silence response/store = %d %s %+v", response.Code, response.Body, operations)
	}
}

func TestAlertRejectsViewerAndMalformedInputs(t *testing.T) {
	tests := []struct {
		name   string
		method string
		path   string
		token  string
		body   string
	}{
		{
			name: "viewer mutation", method: http.MethodPost,
			path:  "/api/v1/alerts/a/acknowledge",
			token: testToken(t, []string{"site-a"}), body: `{"expected_version":1}`,
		},
		{
			name: "unknown query", method: http.MethodGet,
			path:  "/api/v1/alerts?site_id=site-a&extra=true",
			token: testToken(t, []string{"site-a"}),
		},
		{
			name: "duplicate query", method: http.MethodGet,
			path:  "/api/v1/alerts?site_id=site-a&site_id=site-b",
			token: testToken(t, []string{"site-a"}),
		},
		{
			name: "unknown JSON", method: http.MethodPost,
			path:  "/api/v1/alerts/a/acknowledge",
			token: testRoleToken(t, []string{"site-a"}, "operator"),
			body:  `{"expected_version":1,"extra":true}`,
		},
		{
			name: "invalid silence", method: http.MethodPost,
			path:  "/api/v1/alerts/a/silence",
			token: testRoleToken(t, []string{"site-a"}, "operator"),
			body:  `{"expected_version":1,"until":"2000-01-01T00:00:00Z","reason":"old"}`,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			operations := &fakeAlerts{}
			handler := NewRouter(
				&fakeRegistry{}, testValidator(t), &fakeMetrics{}, nil, operations,
			)
			response := performRequestBody(
				handler, test.method, test.path, test.token, test.body,
			)
			want := http.StatusBadRequest
			if test.name == "viewer mutation" {
				want = http.StatusForbidden
			}
			if response.Code != want ||
				operations.listCalls+operations.acknowledgeCalls+operations.silenceCalls != 0 {
				t.Fatalf("response/store = %d %s %+v", response.Code, response.Body, operations)
			}
		})
	}
}

func TestAlertMapsNonDisclosingAndConflictErrors(t *testing.T) {
	tests := []struct {
		err      error
		status   int
		wantCode string
	}{
		{alertops.ErrNotFound, http.StatusNotFound, "not_found"},
		{alertops.ErrConflict, http.StatusConflict, "conflict"},
		{alertops.ErrUnavailable, http.StatusServiceUnavailable, "unavailable"},
	}
	for _, test := range tests {
		operations := &fakeAlerts{err: test.err}
		handler := NewRouter(
			&fakeRegistry{}, testValidator(t), &fakeMetrics{}, nil, operations,
		)
		response := performRequest(
			handler, http.MethodGet, "/api/v1/alerts?site_id=site-a",
			testToken(t, []string{"site-a"}),
		)
		if response.Code != test.status ||
			!strings.Contains(response.Body.String(), `"code":"`+test.wantCode+`"`) {
			t.Fatalf("error %v response = %d %s", test.err, response.Code, response.Body)
		}
	}
}
