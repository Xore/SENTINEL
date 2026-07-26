package metricquery

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func testQuery() Query {
	end := time.Now().UTC().Truncate(time.Second)
	return Query{
		Metric:      "sentinel_collector_heartbeat_total",
		SiteID:      "site-a",
		CollectorID: "dev-node-1",
		Start:       end.Add(-time.Minute),
		End:         end,
		Step:        30 * time.Second,
	}
}

func TestQueryRangeUsesExtraLabelsAndReturnsMatrix(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(
		response http.ResponseWriter, request *http.Request,
	) {
		if request.URL.Path != "/api/v1/query_range" || request.Method != http.MethodPost {
			t.Errorf("unexpected request: %s %s", request.Method, request.URL.Path)
		}
		if err := request.ParseForm(); err != nil {
			t.Error(err)
		}
		if got := request.Form["extra_label"]; len(got) != 2 ||
			got[0] != "site_id=site-a" || got[1] != "collector_id=dev-node-1" {
			t.Errorf("unexpected extra labels: %v", got)
		}
		if request.Form.Get("query") != "sentinel_collector_heartbeat_total" ||
			request.Form.Get("deny_partial_response") != "1" {
			t.Errorf("unexpected query form: %v", request.Form)
		}
		response.Header().Set("Content-Type", "application/json")
		fmt.Fprint(response, `{"status":"success","data":{"resultType":"matrix","result":[`+
			`{"metric":{"__name__":"sentinel_collector_heartbeat_total",`+
			`"site_id":"site-a","collector_id":"dev-node-1"},`+
			`"values":[[1720000000,"1"]]}`+
			`]}}`)
	}))
	defer server.Close()

	client, err := NewClient(server.URL, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	result, err := client.QueryRange(context.Background(), testQuery())
	if err != nil {
		t.Fatal(err)
	}
	if result.ResultType != "matrix" || len(result.Series) != 1 ||
		len(result.Series[0].Values) != 1 {
		t.Fatalf("unexpected result: %+v", result)
	}
}

func TestQueryRangeRejectsIdentityMismatchAndOversizedBody(t *testing.T) {
	tests := map[string]http.HandlerFunc{
		"identity mismatch": func(response http.ResponseWriter, _ *http.Request) {
			fmt.Fprint(response, `{"status":"success","data":{"resultType":"matrix","result":[`+
				`{"metric":{"site_id":"site-b","collector_id":"dev-node-1"},"values":[]}`+
				`]}}`)
		},
		"oversized": func(response http.ResponseWriter, _ *http.Request) {
			fmt.Fprint(response, strings.Repeat("x", maxResponseBytes+1))
		},
	}
	for name, handler := range tests {
		t.Run(name, func(t *testing.T) {
			server := httptest.NewServer(handler)
			defer server.Close()
			client, err := NewClient(server.URL, time.Second)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := client.QueryRange(context.Background(), testQuery()); err == nil {
				t.Fatal("QueryRange() succeeded, want rejection")
			}
		})
	}
}

func TestNewClientRejectsUnsafeURLs(t *testing.T) {
	for _, raw := range []string{
		"",
		"ftp://metrics:21",
		"http://user:secret@metrics:8428",
		"http://metrics:8428?query=up",
	} {
		if _, err := NewClient(raw, time.Second); err == nil {
			t.Fatalf("NewClient(%q) succeeded", raw)
		}
	}
}
