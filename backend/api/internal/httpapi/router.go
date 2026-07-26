// Package httpapi exposes the versioned site REST API.
package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"time"

	"github.com/Xore/analyseLaptop/backend/api/internal/auth"
	"github.com/Xore/analyseLaptop/backend/api/internal/registry"
	"github.com/gin-gonic/gin"
)

const principalKey = "sentinel.principal"

// Registry is the storage boundary used by the HTTP API.
type Registry interface {
	Ping(context.Context) error
	ListCollectors(context.Context, registry.Access) ([]registry.Collector, error)
}

// NewRouter constructs the site API handler.
func NewRouter(store Registry, validator *auth.Validator) http.Handler {
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
		principal, ok := ctx.MustGet(principalKey).(auth.Principal)
		if !ok {
			writeError(ctx, http.StatusUnauthorized, "unauthorized", "authentication required")
			return
		}
		collectors, err := store.ListCollectors(ctx.Request.Context(), registry.Access{
			UserID:   principal.UserID,
			Role:     principal.Role,
			SiteIDs:  principal.SiteIDs,
			IssuedAt: principal.IssuedAt,
		})
		if err != nil {
			writeError(ctx, http.StatusServiceUnavailable, "unavailable", "service unavailable")
			return
		}
		ctx.JSON(http.StatusOK, gin.H{"data": collectors})
	})
	return router
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
