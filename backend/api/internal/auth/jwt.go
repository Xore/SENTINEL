// Package auth validates bearer JWTs for the site API.
package auth

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const maxAuthorizedSites = 64

var siteIDPattern = regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

var validRoles = map[string]struct{}{
	"viewer":      {},
	"operator":    {},
	"analyst":     {},
	"admin":       {},
	"ot-operator": {},
}

// Principal is the validated authentication context used for data scoping.
type Principal struct {
	UserID    string
	Role      string
	SiteIDs   []string
	IssuedAt  time.Time
	ExpiresAt time.Time
}

type claims struct {
	Role    string   `json:"role"`
	SiteIDs []string `json:"site_ids"`
	jwt.RegisteredClaims
}

// Validator parses tokens signed with one configured HS256 key.
type Validator struct {
	secret   []byte
	issuer   string
	audience string
}

// NewValidator creates a strict JWT validator.
func NewValidator(secret []byte, issuer, audience string) (*Validator, error) {
	if len(secret) < 32 {
		return nil, errors.New("JWT secret must contain at least 32 bytes")
	}
	if issuer == "" || audience == "" {
		return nil, errors.New("JWT issuer and audience must not be empty")
	}
	return &Validator{
		secret:   append([]byte(nil), secret...),
		issuer:   issuer,
		audience: audience,
	}, nil
}

// ValidateAuthorization validates an HTTP Authorization header.
func (v *Validator) ValidateAuthorization(header string) (Principal, error) {
	scheme, raw, ok := strings.Cut(strings.TrimSpace(header), " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") || strings.TrimSpace(raw) == "" {
		return Principal{}, errors.New("bearer token required")
	}

	tokenClaims := &claims{}
	token, err := jwt.ParseWithClaims(
		strings.TrimSpace(raw),
		tokenClaims,
		func(token *jwt.Token) (any, error) {
			if token.Method != jwt.SigningMethodHS256 {
				return nil, fmt.Errorf("unexpected signing method %q", token.Method.Alg())
			}
			return v.secret, nil
		},
		jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()}),
		jwt.WithIssuer(v.issuer),
		jwt.WithAudience(v.audience),
		jwt.WithExpirationRequired(),
		jwt.WithIssuedAt(),
		jwt.WithLeeway(30*time.Second),
	)
	if err != nil || !token.Valid {
		return Principal{}, errors.New("invalid bearer token")
	}
	if tokenClaims.Subject == "" || tokenClaims.IssuedAt == nil ||
		tokenClaims.NotBefore == nil || tokenClaims.ExpiresAt == nil {
		return Principal{}, errors.New("required token claims missing")
	}
	if _, ok := validRoles[tokenClaims.Role]; !ok {
		return Principal{}, errors.New("invalid role claim")
	}

	sites, err := normalizeSites(tokenClaims.SiteIDs)
	if err != nil {
		return Principal{}, err
	}
	return Principal{
		UserID:    tokenClaims.Subject,
		Role:      tokenClaims.Role,
		SiteIDs:   sites,
		IssuedAt:  tokenClaims.IssuedAt.Time,
		ExpiresAt: tokenClaims.ExpiresAt.Time,
	}, nil
}

func normalizeSites(input []string) ([]string, error) {
	if len(input) == 0 || len(input) > maxAuthorizedSites {
		return nil, errors.New("invalid site scope")
	}
	seen := make(map[string]struct{}, len(input))
	sites := make([]string, 0, len(input))
	for _, siteID := range input {
		if !siteIDPattern.MatchString(siteID) {
			return nil, errors.New("invalid site scope")
		}
		if _, exists := seen[siteID]; exists {
			continue
		}
		seen[siteID] = struct{}{}
		sites = append(sites, siteID)
	}
	return sites, nil
}
