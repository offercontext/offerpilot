package db

import (
	"os"
	"reflect"
	"regexp"
	"testing"
)

func TestFrontendStatusContractsMatchDatabaseStatuses(t *testing.T) {
	assertTSUnionMatches(t, "../../web/src/types/application.ts", "ApplicationStatus", ApplicationStatuses)
	assertTSUnionMatches(t, "../../web/src/types/offer.ts", "OfferStatus", OfferStatuses)
	assertTSUnionMatches(t, "../../web/src/types/question.ts", "QuestionDifficulty", QuestionDifficulties)
	assertTSUnionMatches(t, "../../web/src/types/question.ts", "QuestionStatus", QuestionStatuses)
	assertTSUnionMatches(t, "../../web/src/types/question.ts", "QuestionSource", QuestionSources)
}

func assertTSUnionMatches(t *testing.T, path string, typeName string, want []string) {
	t.Helper()
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	typeRe := regexp.MustCompile(`export\s+type\s+` + regexp.QuoteMeta(typeName) + `\s*=\s*([^;]+);`)
	match := typeRe.FindSubmatch(content)
	if match == nil {
		t.Fatalf("%s union not found in %s", typeName, path)
	}
	valueRe := regexp.MustCompile(`'([^']+)'`)
	matches := valueRe.FindAllSubmatch(match[1], -1)
	var got []string
	for _, m := range matches {
		got = append(got, string(m[1]))
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("%s mismatch:\n got %v\nwant %v", typeName, got, want)
	}
}
