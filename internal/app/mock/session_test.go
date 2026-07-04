package mock

import "testing"

func TestTitleForSessionConfig(t *testing.T) {
	tests := []struct {
		name string
		cfg  SessionConfig
		want string
	}{
		{
			name: "explicit title wins",
			cfg:  SessionConfig{Title: "Frontend screen"},
			want: "Frontend screen",
		},
		{
			name: "company and role",
			cfg:  SessionConfig{Company: "ByteDance", Role: "Backend"},
			want: "ByteDance · Backend",
		},
		{
			name: "role only",
			cfg:  SessionConfig{Role: "Backend"},
			want: "Backend",
		},
		{
			name: "fallback title",
			cfg:  SessionConfig{},
			want: DefaultSessionTitle,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := TitleForSessionConfig(tt.cfg); got != tt.want {
				t.Fatalf("TitleForSessionConfig() = %q, want %q", got, tt.want)
			}
		})
	}
}
