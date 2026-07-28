// Package httpapi exposes the versioned site REST API.
package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Xore/analyseLaptop/backend/api/internal/auth"
	"github.com/Xore/analyseLaptop/backend/api/internal/maintenance"
	"github.com/Xore/analyseLaptop/backend/api/internal/metricquery"
	"github.com/Xore/analyseLaptop/backend/api/internal/registry"
	"github.com/gin-gonic/gin"
)

const principalKey = "sentinel.principal"

// Registry is the storage boundary used by the HTTP API.
type Registry interface {
	Ping(context.Context) error
	ListCollectors(context.Context, registry.Access) ([]registry.Collector, error)
	AuthorizeSite(context.Context, registry.Access, string) (bool, error)
}

// MetricsQuery is the site-scoped time-series query boundary.
type MetricsQuery interface {
	QueryRange(context.Context, metricquery.Query) (metricquery.Result, error)
}

// MaintenanceStore is the durable operations boundary used by the HTTP API.
type MaintenanceStore interface {
	Create(context.Context, maintenance.Access, maintenance.CreateInput) (maintenance.Window, error)
	List(context.Context, maintenance.Access, maintenance.ListFilter) ([]maintenance.Window, error)
	End(
		context.Context,
		maintenance.Access,
		string,
		maintenance.EndInput,
	) (maintenance.Window, error)
}

// NewRouter constructs the site API handler.
func NewRouter(
	store Registry,
	validator *auth.Validator,
	metrics MetricsQuery,
	maintenanceStore MaintenanceStore,
) http.Handler {
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery(), requestID(), securityHeaders())

	router.GET("/healthz", func(ctx *gin.Context) {
		ctx.JSON(http.StatusOK, gin.H{"status": "ok"})
	})
	router.GET("/readyz", func(ctx *gin.Context) {
		if err := store.Ping(ctx.Request.Context()); err != nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		ctx.JSON(http.StatusOK, gin.H{"status": "ready"})
	})

	api := router.Group("/api/v1")
	api.Use(authenticate(validator))
	api.GET("/collectors", func(ctx *gin.Context) {
		principal, ok := ctx.Get(principalKey)
		if !ok {
			writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
			return
		}
		typedPrincipal, ok := principal.(auth.Principal)
		if !ok {
			writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
			return
		}
		collectors, err := store.ListCollectors(ctx.Request.Context(), registry.Access{
			UserID:   typedPrincipal.UserID,
			Role:     typedPrincipal.Role,
			SiteIDs:  typedPrincipal.SiteIDs,
			IssuedAt: typedPrincipal.IssuedAt,
		})
		if err != nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		ctx.JSON(http.StatusOK, gin.H{"data": collectors})
	})
	api.GET("/metrics/range", func(ctx *gin.Context) {
		query, err := metricquery.Parse(ctx.Request.URL.Query(), time.Now().UTC())
		if err != nil {
			writeError(ctx, http.StatusBadRequest, "invalid_request", "invalid query parameters")
			return
		}
		principal, ok := ctx.Get(principalKey)
		if !ok {
			writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
			return
		}
		typedPrincipal, ok := principal.(auth.Principal)
		if !ok {
			writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
			return
		}
		access := registry.Access{
			UserID:   typedPrincipal.UserID,
			Role:     typedPrincipal.Role,
			SiteIDs:  typedPrincipal.SiteIDs,
			IssuedAt: typedPrincipal.IssuedAt,
		}
		authorized, err := store.AuthorizeSite(ctx.Request.Context(), access, query.SiteID)
		if err != nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		if !authorized {
			writeError(ctx, http.StatusNotFound, "not_found", "resource not found")
			return
		}
		if metrics == nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		result, err := metrics.QueryRange(ctx.Request.Context(), query)
		if err != nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		ctx.JSON(http.StatusOK, gin.H{"data": result})
	})
	api.GET("/maintenance-windows", func(ctx *gin.Context) {
		principal, ok := currentPrincipal(ctx)
		if !ok {
			return
		}
		limit := 0
		if rawLimit := ctx.Query("limit"); rawLimit != "" {
			parsed, err := strconv.Atoi(rawLimit)
			if err != nil {
				writeError(ctx, http.StatusBadRequest, "invalid_request", "invalid query parameters")
				return
			}
			limit = parsed
		}
		filter, err := maintenance.ValidateList(maintenance.ListFilter{
			SiteID: ctx.Query("site_id"),
			State:  ctx.Query("state"),
			Limit:  limit,
		})
		if err != nil || hasUnknownQuery(ctx, "site_id", "state", "limit") {
			writeError(ctx, http.StatusBadRequest, "invalid_request", "invalid query parameters")
			return
		}
		if maintenanceStore == nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		windows, err := maintenanceStore.List(
			ctx.Request.Context(), maintenanceAccess(principal), filter,
		)
		if err != nil {
			writeMaintenanceError(ctx, err)
			return
		}
		ctx.JSON(http.StatusOK, gin.H{"data": windows})
	})
	api.POST("/maintenance-windows", func(ctx *gin.Context) {
		principal, ok := currentPrincipal(ctx)
		if !ok {
			return
		}
		if !maintenance.CanMutate(principal.Role) {
			writeError(ctx, http.StatusForbidden, "forbidden", "operation not permitted")
			return
		}
		var input maintenance.CreateInput
		if err := decodeJSON(ctx, &input); err != nil {
			writeError(ctx, http.StatusBadRequest, "invalid_request", "invalid request body")
			return
		}
		normalized, err := maintenance.ValidateCreate(input)
		if err != nil {
			writeError(ctx, http.StatusBadRequest, "invalid_request", "invalid request body")
			return
		}
		if maintenanceStore == nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		window, err := maintenanceStore.Create(
			ctx.Request.Context(), maintenanceAccess(principal), normalized,
		)
		if err != nil {
			writeMaintenanceError(ctx, err)
			return
		}
		ctx.Header("Location", "/api/v1/maintenance-windows/"+window.ID)
		ctx.JSON(http.StatusCreated, gin.H{"data": window})
	})
	api.POST("/maintenance-windows/:id/end", func(ctx *gin.Context) {
		principal, ok := currentPrincipal(ctx)
		if !ok {
			return
		}
		if !maintenance.CanMutate(principal.Role) {
			writeError(ctx, http.StatusForbidden, "forbidden", "operation not permitted")
			return
		}
		var input maintenance.EndInput
		if err := decodeJSON(ctx, &input); err != nil || maintenance.ValidateEnd(input) != nil {
			writeError(ctx, http.StatusBadRequest, "invalid_request", "invalid request body")
			return
		}
		if maintenanceStore == nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		window, err := maintenanceStore.End(
			ctx.Request.Context(),
			maintenanceAccess(principal),
			ctx.Param("id"),
			input,
		)
		if err != nil {
			writeMaintenanceError(ctx, err)
			return
		}
		ctx.JSON(http.StatusOK, gin.H{"data": window})
	})
	return router
}

func currentPrincipal(ctx *gin.Context) (auth.Principal, bool) {
	principal, ok := ctx.Get(principalKey)
	if !ok {
		writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
		return auth.Principal{}, false
	}
	typed, ok := principal.(auth.Principal)
	if !ok {
		writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
		return auth.Principal{}, false
	}
	return typed, true
}

func maintenanceAccess(principal auth.Principal) maintenance.Access {
	return maintenance.Access{
		UserID:   principal.UserID,
		Role:     principal.Role,
		SiteIDs:  principal.SiteIDs,
		IssuedAt: principal.IssuedAt,
	}
}

func decodeJSON(ctx *gin.Context, destination any) error {
	ctx.Request.Body = http.MaxBytesReader(ctx.Writer, ctx.Request.Body, 8*1024)
	decoder := json.NewDecoder(ctx.Request.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("request body must contain one JSON object")
	}
	return nil
}

func hasUnknownQuery(ctx *gin.Context, allowed ...string) bool {
	known := make(map[string]struct{}, len(allowed))
	for _, name := range allowed {
		known[name] = struct{}{}
	}
	for name, values := range ctx.Request.URL.Query() {
		if _, ok := known[name]; !ok || len(values) != 1 || strings.TrimSpace(values[0]) == "" {
			return true
		}
	}
	return false
}

func writeMaintenanceError(ctx *gin.Context, err error) {
	switch {
	case errors.Is(err, maintenance.ErrInvalid):
		writeError(ctx, http.StatusBadRequest, "invalid_request", "invalid maintenance operation")
	case errors.Is(err, maintenance.ErrForbidden):
		writeError(ctx, http.StatusForbidden, "forbidden", "operation not permitted")
	case errors.Is(err, maintenance.ErrNotFound):
		writeError(ctx, http.StatusNotFound, "not_found", "resource not found")
	case errors.Is(err, maintenance.ErrConflict):
		writeError(ctx, http.StatusConflict, "conflict", "resource version conflict")
	default:
		writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
	}
}

func authenticate(validator *auth.Validator) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		if validator == nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			ctx.Abort()
			return
		}
		principal, err := validator.ValidateAuthorization(ctx.GetHeader("Authorization"))
		if err != nil {
			writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
			ctx.Abort()
			return
		}
		ctx.Set(principalKey, principal)
		ctx.Next()
	}
}

func requestID() gin.HandlerFunc {
	return func(ctx *gin.Context) {
		requestID := newRequestID()
		ctx.Header("X-Request-ID", requestID)
		ctx.Set("request_id", requestID)
		ctx.Next()
	}
}

func securityHeaders() gin.HandlerFunc {
	return func(ctx *gin.Context) {
		ctx.Header("Cache-Control", "no-store")
		ctx.Header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
		ctx.Header("X-Content-Type-Options", "nosniff")
		ctx.Header("X-Frame-Options", "DENY")
		ctx.Next()
	}
}

func newRequestID() string {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return time.Now().UTC().Format("20060102T150405.000000000")
	}
	return hex.EncodeToString(value[:])
}

func writeError(ctx *gin.Context, status int, code, message string) {
	requestID, _ := ctx.Get("request_id")
	ctx.JSON(status, gin.H{
		"error": gin.H{
			"code":       code,
			"message":    message,
			"request_id": requestID,
		},
	})
}
