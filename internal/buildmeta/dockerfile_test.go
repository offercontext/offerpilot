package buildmeta

import (
	"os"
	"strings"
	"testing"
)

func TestDockerfileCopiesFrontendDistFromBuildStage(t *testing.T) {
	dockerignore, err := os.ReadFile("../../.dockerignore")
	if err != nil {
		t.Fatalf("read .dockerignore: %v", err)
	}
	if !strings.Contains(string(dockerignore), "web/dist/") {
		t.Skip(".dockerignore does not exclude web/dist")
	}

	dockerfile, err := os.ReadFile("../../Dockerfile")
	if err != nil {
		t.Fatalf("read Dockerfile: %v", err)
	}
	content := string(dockerfile)
	if strings.Contains(content, "\nCOPY web/dist /app/web/dist") {
		t.Fatalf("Dockerfile copies ignored web/dist from build context")
	}
	if !strings.Contains(content, "COPY --from=web /web/dist /app/web/dist") {
		t.Fatalf("Dockerfile must copy frontend dist from the web build stage")
	}
}
