package mock

const DefaultSessionTitle = "模拟面试"

type SessionConfig struct {
	Title   string
	Role    string
	Company string
}

func TitleForSessionConfig(cfg SessionConfig) string {
	if cfg.Title != "" {
		return cfg.Title
	}
	name := cfg.Role
	if name == "" {
		name = DefaultSessionTitle
	}
	if cfg.Company != "" {
		name = cfg.Company + " · " + name
	}
	return name
}
