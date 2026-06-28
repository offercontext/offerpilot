// AI analysis result — mirrors internal/ai.JDAnalysisResult JSON tags.
export interface JDAnalysisResult {
  summary: string;
  requirements: string[];
  tech_stack: string[];
  experience_years: string;
  education: string;
  highlights: string[];
  suggestions: string[];
}

// Resume match result — mirrors internal/ai.MatchResult JSON tags.
export interface MatchResult {
  match_score: number;
  matched: string[];
  gaps: string[];
  suggestions: string[];
  summary: string;
}

// Stored JD analysis row (fields match Go db.JDAnalysis JSON tags);
// `result` is either a parsed object (newly created) or a JSON string (list endpoint).
export interface JDAnalysis {
  id: number;
  application_id?: number;
  jd_source: string;
  jd_text: string;
  result: string;
  created_at: string;
}

export interface AnalyzeJDResponse {
  id: number;
  application_id?: number;
  jd_source: string;
  result: JDAnalysisResult;
}