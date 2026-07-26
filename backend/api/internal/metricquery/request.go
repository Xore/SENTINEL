package metricquery

import (
	"errors"
	"net/url"
	"regexp"
	"strconv"
	"time"
)

const (
	maxRange       = 24 * time.Hour
	minStep        = 10 * time.Second
	maxStep        = time.Hour
	maxPoints      = 2_000
	maxFutureClock = 5 * time.Minute
)

var identifierPattern = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

var metricCatalog = map[string]struct{}{
	"sentinel_collector_heartbeat_total":               {},
	"sentinel_collector_check_runs_total":              {},
	"sentinel_collector_check_duration_seconds":        {},
	"sentinel_collector_check_duration_seconds_bucket": {},
	"sentinel_collector_check_duration_seconds_count":  {},
	"sentinel_collector_check_duration_seconds_sum":    {},
	"sentinel_collector_export_failures_total":         {},
	"sentinel_collector_cycle_duration_seconds":        {},
	"sentinel_collector_cycle_duration_seconds_bucket": {},
	"sentinel_collector_cycle_duration_seconds_count":  {},
	"sentinel_collector_cycle_duration_seconds_sum":    {},
	"sentinel_collector_event_loop_lag_seconds":        {},
}

// Parse validates an API query without accepting arbitrary MetricsQL text.
func Parse(values url.Values, now time.Time) (Query, error) {
	if len(values) > 6 {
		return Query{}, errors.New("unknown query parameter")
	}
	for key := range values {
		switch key {
		case "metric", "site_id", "collector_id", "start", "end", "step":
		default:
			return Query{}, errors.New("unknown query parameter")
		}
		if len(values[key]) != 1 {
			return Query{}, errors.New("duplicate query parameter")
		}
	}

	metric := values.Get("metric")
	if _, ok := metricCatalog[metric]; !ok {
		return Query{}, errors.New("metric is not queryable")
	}
	siteID := values.Get("site_id")
	collectorID := values.Get("collector_id")
	if !identifierPattern.MatchString(siteID) ||
		(collectorID != "" && !identifierPattern.MatchString(collectorID)) {
		return Query{}, errors.New("invalid identifier")
	}
	start, err := time.Parse(time.RFC3339, values.Get("start"))
	if err != nil {
		return Query{}, errors.New("invalid start")
	}
	end, err := time.Parse(time.RFC3339, values.Get("end"))
	if err != nil {
		return Query{}, errors.New("invalid end")
	}
	stepSeconds, err := strconv.ParseInt(values.Get("step"), 10, 64)
	if err != nil || stepSeconds < int64(minStep/time.Second) ||
		stepSeconds > int64(maxStep/time.Second) {
		return Query{}, errors.New("invalid step")
	}
	step := time.Duration(stepSeconds) * time.Second
	span := end.Sub(start)
	if span <= 0 || span > maxRange || end.After(now.Add(maxFutureClock)) {
		return Query{}, errors.New("invalid range")
	}
	if span/step+1 > maxPoints {
		return Query{}, errors.New("invalid step")
	}
	return Query{
		Metric:      metric,
		SiteID:      siteID,
		CollectorID: collectorID,
		Start:       start,
		End:         end,
		Step:        step,
	}, nil
}
