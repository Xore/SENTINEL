package enrollment

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
)

const maxRequestBytes = 64 << 10

type enroller interface {
	Enroll(context.Context, Request) (Response, error)
}

// Handler exposes the enrollment service over its bootstrap-token HTTP API.
type Handler struct {
	service enroller
}

// NewHandler creates the production enrollment HTTP handler.
func NewHandler(service enroller) *Handler {
	return &Handler{service: service}
}

func (h *Handler) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	writer.Header().Set("Cache-Control", "no-store")
	if request.Method != http.MethodPost {
		writer.Header().Set("Allow", http.MethodPost)
		http.Error(writer, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	token, ok := bearerToken(request.Header.Get("Authorization"))
	if !ok {
		http.Error(writer, "enrollment credentials rejected", http.StatusUnauthorized)
		return
	}

	request.Body = http.MaxBytesReader(writer, request.Body, maxRequestBytes)
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	var body struct {
		SiteID      string `json:"site_id"`
		CollectorID string `json:"collector_id"`
		CSRPEM      string `json:"csr_pem"`
	}
	if err := decoder.Decode(&body); err != nil {
		http.Error(writer, "invalid enrollment request", http.StatusBadRequest)
		return
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		http.Error(writer, "invalid enrollment request", http.StatusBadRequest)
		return
	}

	response, err := h.service.Enroll(request.Context(), Request{
		Token:       token,
		SiteID:      body.SiteID,
		CollectorID: body.CollectorID,
		CSRPEM:      body.CSRPEM,
	})
	switch {
	case errors.Is(err, ErrRejected):
		http.Error(writer, "enrollment credentials rejected", http.StatusUnauthorized)
		return
	case errors.Is(err, ErrInvalidRequest):
		http.Error(writer, "invalid enrollment request", http.StatusUnprocessableEntity)
		return
	case err != nil:
		http.Error(writer, "enrollment service unavailable", http.StatusServiceUnavailable)
		return
	}

	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(writer).Encode(response)
}

func bearerToken(value string) (string, bool) {
	scheme, token, ok := strings.Cut(value, " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") || token == "" ||
		strings.ContainsAny(token, " \t\r\n,") {
		return "", false
	}
	return token, true
}
