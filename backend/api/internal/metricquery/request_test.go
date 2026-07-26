package metricquery

import (
	"net/url"
	"testing"
	"time"
)

func validValues(now time.Time) url.Values {
	return url.Values{
		"metric":       {"sentinel_collector_heartbeat_total"},
		"site_id":      {"site-a"},
		"collector_id": {"dev-node-1"},
		"start":        {now.Add(-time.Hour).Format(time.RFC3339)},
		"end":          {now.Format(time.RFC3339)},
		"step":         {"30"},
	}
}

func TestParseAcceptsBoundedCatalogQuery(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	query, err := Parse(validValues(now), now)
	if err != nil {
		t.Fatal(err)
	}
	if query.SiteID != "site-a" || query.CollectorID != "dev-node-1" ||
		query.Step != 30*time.Second {
		t.Fatalf("unexpected query: %+v", query)
	}
}

func TestParseRejectsUnsafeInputs(t *testing.T) {
	now := time.Now().UTC().Truncate(time.Second)
	tests := map[string]func(url.Values){
		"arbitrary MetricsQL": func(values url.Values) {
			values.Set("metric", `rate(http_requests_total[5m])`)
		},
		"unknown metric": func(values url.Values) {
			values.Set("metric", "process_cpu_seconds_total")
		},
		"invalid site": func(values url.Values) {
			values.Set("site_id", `site-a"} or {site_id="site-b`)
		},
		"range too large": func(values url.Values) {
			values.Set("start", now.Add(-25*time.Hour).Format(time.RFC3339))
		},
		"too many points": func(values url.Values) {
			values.Set("start", now.Add(-24*time.Hour).Format(time.RFC3339))
			values.Set("step", "10")
		},
		"future end": func(values url.Values) {
			values.Set("end", now.Add(6*time.Minute).Format(time.RFC3339))
		},
		"overflow step": func(values url.Values) {
			values.Set("step", "9223372036854775807")
		},
		"duplicate": func(values url.Values) {
			values["site_id"] = []string{"site-a", "site-b"}
		},
		"unknown parameter": func(values url.Values) {
			values.Set("query", "up")
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			values := validValues(now)
			mutate(values)
			if _, err := Parse(values, now); err == nil {
				t.Fatal("Parse() succeeded, want rejection")
			}
		})
	}
}
