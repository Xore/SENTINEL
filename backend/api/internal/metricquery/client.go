// Package metricquery performs bounded, site-scoped VictoriaMetrics queries.
package metricquery

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

const (
	maxResponseBytes = 4 << 20
	maxSeries        = 500
	maxSamples       = 50_000
)

// ErrUnavailable indicates that VictoriaMetrics did not return a safe result.
var ErrUnavailable = errors.New("metrics query unavailable")

// Query is an already validated, site-scoped range query.
type Query struct {
	Metric      string
	SiteID      string
	CollectorID string
	Start       time.Time
	End         time.Time
	Step        time.Duration
}

// Result is the safe subset of a Prometheus matrix response returned by the API.
type Result struct {
	ResultType string   `json:"result_type"`
	Series     []Series `json:"result"`
}

// Series is one labelled time series and its Prometheus-format samples.
type Series struct {
	Metric map[string]string   `json:"metric"`
	Values [][]json.RawMessage `json:"values"`
}

// Client is a bounded VictoriaMetrics range-query client.
type Client struct {
	endpoint   string
	httpClient *http.Client
	timeout    time.Duration
}

// NewClient validates the VictoriaMetrics base URL and returns a query client.
func NewClient(baseURL string, timeout time.Duration) (*Client, error) {
	parsed, err := url.Parse(baseURL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") ||
		parsed.Host == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("invalid VictoriaMetrics query URL")
	}
	if timeout <= 0 {
		return nil, errors.New("metrics query timeout must be positive")
	}
	parsed.Path = joinURLPath(parsed.Path, "/api/v1/query_range")
	return &Client{
		endpoint:   parsed.String(),
		httpClient: &http.Client{Timeout: timeout},
		timeout:    timeout,
	}, nil
}

// QueryRange executes q while enforcing response size and identity bounds.
func (c *Client) QueryRange(ctx context.Context, q Query) (Result, error) {
	if c == nil || c.httpClient == nil {
		return Result{}, ErrUnavailable
	}
	form := url.Values{
		"query":                 {q.Metric},
		"start":                 {q.Start.UTC().Format(time.RFC3339Nano)},
		"end":                   {q.End.UTC().Format(time.RFC3339Nano)},
		"step":                  {strconv.FormatFloat(q.Step.Seconds(), 'f', -1, 64)},
		"timeout":               {strconv.FormatFloat(c.timeout.Seconds(), 'f', -1, 64) + "s"},
		"deny_partial_response": {"1"},
	}
	form.Add("extra_label", "site_id="+q.SiteID)
	if q.CollectorID != "" {
		form.Add("extra_label", "collector_id="+q.CollectorID)
	}

	request, err := http.NewRequestWithContext(
		ctx,
		http.MethodPost,
		c.endpoint,
		bytes.NewBufferString(form.Encode()),
	)
	if err != nil {
		return Result{}, ErrUnavailable
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set("Accept", "application/json")

	response, err := c.httpClient.Do(request)
	if err != nil {
		return Result{}, ErrUnavailable
	}
	defer response.Body.Close()
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		return Result{}, ErrUnavailable
	}

	body, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil || len(body) > maxResponseBytes {
		return Result{}, ErrUnavailable
	}
	var upstream struct {
		Status string `json:"status"`
		Data   struct {
			ResultType string   `json:"resultType"`
			Result     []Series `json:"result"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &upstream); err != nil ||
		upstream.Status != "success" || upstream.Data.ResultType != "matrix" {
		return Result{}, ErrUnavailable
	}
	if len(upstream.Data.Result) > maxSeries {
		return Result{}, ErrUnavailable
	}

	sampleCount := 0
	for _, series := range upstream.Data.Result {
		if series.Metric["site_id"] != q.SiteID ||
			(q.CollectorID != "" && series.Metric["collector_id"] != q.CollectorID) {
			return Result{}, ErrUnavailable
		}
		for _, sample := range series.Values {
			if len(sample) != 2 {
				return Result{}, ErrUnavailable
			}
		}
		sampleCount += len(series.Values)
		if sampleCount > maxSamples {
			return Result{}, ErrUnavailable
		}
	}
	return Result{
		ResultType: upstream.Data.ResultType,
		Series:     upstream.Data.Result,
	}, nil
}

func joinURLPath(base, suffix string) string {
	if base == "" || base == "/" {
		return suffix
	}
	if base[len(base)-1] == '/' {
		base = base[:len(base)-1]
	}
	return fmt.Sprintf("%s%s", base, suffix)
}
