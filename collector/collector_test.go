package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net"
	"runtime"
	"testing"
)

// sign reproduces the backend's _sign_update() so tests can mint a legitimate
// instruction. If this and authorizeUpdate ever disagree, a real agent would
// reject a real update - so this doubling is the point.
func sign(secret, version, osArch, sha string) string {
	m := hmac.New(sha256.New, []byte(secret))
	m.Write([]byte(fmt.Sprintf("%s\n%s\n%s", version, osArch, sha)))
	return hex.EncodeToString(m.Sum(nil))
}

func TestVersionNewer(t *testing.T) {
	cases := []struct {
		a, b string
		want bool
	}{
		{"0.2.0", "0.1.0", true},
		{"0.2.0", "0.2.0", false},
		{"0.1.9", "0.2.0", false},
		{"1.0.0", "0.9.9", true},
		{"0.2.1", "0.2.0", true},
		{"0.2", "0.2.0", false},
	}
	for _, c := range cases {
		if got := versionNewer(c.a, c.b); got != c.want {
			t.Errorf("versionNewer(%q,%q)=%v want %v", c.a, c.b, got, c.want)
		}
	}
}

func TestAuthorizeUpdate(t *testing.T) {
	const secret = "s3cr3t-signing-key"
	const cur = "0.1.0"
	const target = "0.2.0"
	const sha = "abc123def456"
	osArch := runtime.GOOS + "/" + runtime.GOARCH
	goodSig := sign(secret, target, osArch, sha)

	good := func() map[string]any {
		return map[string]any{"version": target, "sha256": sha, "sig": goodSig}
	}

	t.Run("valid instruction is authorized", func(t *testing.T) {
		gotT, gotSHA, ok, reason := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, good())
		if !ok {
			t.Fatalf("expected authorized, got refused: %s", reason)
		}
		if gotT != target || gotSHA != sha {
			t.Fatalf("target/sha mismatch: %q %q", gotT, gotSHA)
		}
	})

	t.Run("forged signature is refused", func(t *testing.T) {
		u := good()
		u["sig"] = "deadbeef"
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("forged signature was accepted")
		}
	})

	t.Run("wrong secret is refused", func(t *testing.T) {
		if _, _, ok, _ := authorizeUpdate("other-secret", runtime.GOOS, runtime.GOARCH, cur, good()); ok {
			t.Fatal("update signed with a different secret was accepted")
		}
	})

	t.Run("no secret configured refuses", func(t *testing.T) {
		if _, _, ok, _ := authorizeUpdate("", runtime.GOOS, runtime.GOARCH, cur, good()); ok {
			t.Fatal("update accepted with no secret configured")
		}
	})

	t.Run("unsigned instruction is refused", func(t *testing.T) {
		u := map[string]any{"version": target, "sha256": sha}
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("unsigned instruction accepted")
		}
	})

	t.Run("downgrade is refused even if validly signed", func(t *testing.T) {
		old := "0.0.9"
		u := map[string]any{"version": old, "sha256": sha,
			"sig": sign(secret, old, osArch, sha)}
		if _, _, ok, reason := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatalf("downgrade accepted: reason=%q", reason)
		}
	})

	t.Run("substituted sha256 breaks the signature", func(t *testing.T) {
		u := good()
		u["sha256"] = "0000000000" // sig no longer matches the digest
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("mismatched sha256 accepted")
		}
	})

	t.Run("cross-platform signature does not verify on our platform", func(t *testing.T) {
		// A MAC minted for a different os/arch must not authorize us, because we
		// rebuild the message from our own platform.
		u := good()
		u["sig"] = sign(secret, target, "plan9/486", sha)
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("signature for another platform authorized us")
		}
	})
}

func TestRunPorts(t *testing.T) {
	// A real listener the port check should find OPEN, plus a closed port.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	host, portStr, _ := net.SplitHostPort(ln.Addr().String())
	var openPort int
	fmt.Sscanf(portStr, "%d", &openPort)

	plan := checkPlan{Ports: []portCheck{
		{Name: "open", Host: host, Port: openPort, Proto: "tcp"},
		{Name: "closed", Host: host, Port: 1, Proto: "tcp"},
	}}
	rows := runPorts(plan, 0)
	if len(rows) != 2 {
		t.Fatalf("want 2 rows, got %d", len(rows))
	}
	byName := map[string]bool{}
	for _, r := range rows {
		byName[r["name"].(string)] = r["open"].(bool)
	}
	if !byName["open"] {
		t.Error("expected the live listener to read as open")
	}
	if byName["closed"] {
		t.Error("expected port 1 to read as closed")
	}
}

func TestCheckTCP(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	if ok, _ := checkTCP(ln.Addr().String()); !ok {
		t.Error("checkTCP should connect to a live listener")
	}
	if ok, _ := checkTCP("127.0.0.1:1"); ok {
		t.Error("checkTCP should fail on a closed port")
	}
}
