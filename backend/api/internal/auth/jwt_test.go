package auth

import (
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const (
	testIssuer   = "sentinel-test"
	testAudience = "sentinel-test-api"
)

var testSecret = []byte(strings.Repeat("s", 32))

func signToken(
	t *testing.T,
	method jwt.SigningMethod,
	secret any,
	role string,
	sites []string,
	now time.Time,
) string {
	t.Helper()
	token := jwt.NewWithClaims(method, claims{
		Role:    role,
		SiteIDs: sites,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   "viewer-1",
			Issuer:    testIssuer,
			Audience:  jwt.ClaimStrings{testAudience},
			IssuedAt:  jwt.NewNumericDate(now),
			NotBefore: jwt.NewNumericDate(now.Add(-time.Minute)),
			ExpiresAt: jwt.NewNumericDate(now.Add(time.Hour)),
		},
	})
	raw, err := token.SignedString(secret)
	if err != nil {
		t.Fatalf("SignedString() error = %v", err)
	}
	return raw
}

func TestValidateAuthorizationAcceptsScopedHS256Token(t *testing.T) {
	validator, err := NewValidator(testSecret, testIssuer, testAudience)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	raw := signToken(
		t, jwt.SigningMethodHS256, testSecret, "viewer", []string{"site-a"}, now,
	)

	principal, err := validator.ValidateAuthorization("Bearer " + raw)
	if err != nil {
		t.Fatalf("ValidateAuthorization() error = %v", err)
	}
	if principal.UserID != "viewer-1" || principal.Role != "viewer" ||
		len(principal.SiteIDs) != 1 || principal.SiteIDs[0] != "site-a" {
		t.Fatalf("unexpected principal: %+v", principal)
	}
}

func TestValidateAuthorizationRejectsWrongAlgorithm(t *testing.T) {
	validator, err := NewValidator(testSecret, testIssuer, testAudience)
	if err != nil {
		t.Fatal(err)
	}
	raw := signToken(
		t, jwt.SigningMethodHS384, testSecret, "viewer", []string{"site-a"}, time.Now(),
	)

	if _, err := validator.ValidateAuthorization("Bearer " + raw); err == nil {
		t.Fatal("ValidateAuthorization() accepted HS384")
	}
}

func TestValidateAuthorizationRejectsExpiredToken(t *testing.T) {
	validator, err := NewValidator(testSecret, testIssuer, testAudience)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().Add(-2 * time.Hour)
	raw := signToken(
		t, jwt.SigningMethodHS256, testSecret, "viewer", []string{"site-a"}, now,
	)

	if _, err := validator.ValidateAuthorization("Bearer " + raw); err == nil {
		t.Fatal("ValidateAuthorization() accepted expired token")
	}
}

func TestValidateAuthorizationRejectsMissingOrInvalidScope(t *testing.T) {
	validator, err := NewValidator(testSecret, testIssuer, testAudience)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name  string
		role  string
		sites []string
	}{
		{name: "role", role: "superuser", sites: []string{"site-a"}},
		{name: "sites", role: "viewer", sites: nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			raw := signToken(
				t, jwt.SigningMethodHS256, testSecret, tc.role, tc.sites, time.Now(),
			)
			if _, err := validator.ValidateAuthorization("Bearer " + raw); err == nil {
				t.Fatal("ValidateAuthorization() accepted invalid scope")
			}
		})
	}
}
