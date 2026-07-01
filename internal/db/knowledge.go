package db

import (
	"database/sql"
	"encoding/json"
	"strings"
	"time"
	"unicode"
)

const (
	KnowledgeSourceManual = "manual"
	KnowledgeSourceUpload = "upload"

	defaultKnowledgeLimit = 5
	maxKnowledgeLimit     = 10
	maxChunkRunes         = 900
	minChunkRunes         = 120
)

type KnowledgeBase struct {
	ID          int64     `json:"id"`
	Name        string    `json:"name"`
	Description string    `json:"description"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type KnowledgeDocument struct {
	ID              int64     `json:"id"`
	KnowledgeBaseID int64     `json:"knowledge_base_id"`
	Title           string    `json:"title"`
	Content         string    `json:"content"`
	Tags            []string  `json:"tags"`
	SourceType      string    `json:"source_type"`
	SourceName      string    `json:"source_name"`
	CreatedAt       time.Time `json:"created_at"`
	UpdatedAt       time.Time `json:"updated_at"`
}

type KnowledgeDocumentFilter struct {
	KnowledgeBaseID int64  `json:"knowledge_base_id"`
	Query           string `json:"query"`
}

type KnowledgeSearchFilter struct {
	Query           string `json:"query"`
	KnowledgeBaseID int64  `json:"knowledge_base_id"`
	Limit           int    `json:"limit"`
}

type KnowledgeSearchResult struct {
	KnowledgeBaseID   int64   `json:"knowledge_base_id"`
	KnowledgeBaseName string  `json:"knowledge_base_name"`
	DocumentID        int64   `json:"document_id"`
	DocumentTitle     string  `json:"document_title"`
	ChunkID           int64   `json:"chunk_id"`
	Snippet           string  `json:"snippet"`
	Score             float64 `json:"score"`
}

// CreateKnowledgeBase inserts a new knowledge base.
func (db *Database) CreateKnowledgeBase(base *KnowledgeBase) error {
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO knowledge_bases (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)`,
		base.Name, base.Description, now, now,
	)
	if err != nil {
		return err
	}
	base.ID, _ = res.LastInsertId()
	base.CreatedAt = now
	base.UpdatedAt = now
	return nil
}

// ListKnowledgeBases lists all knowledge bases.
func (db *Database) ListKnowledgeBases() ([]KnowledgeBase, error) {
	rows, err := db.conn.Query(`SELECT id, name, description, created_at, updated_at FROM knowledge_bases ORDER BY updated_at DESC, id DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var bases []KnowledgeBase
	for rows.Next() {
		var base KnowledgeBase
		if err := rows.Scan(&base.ID, &base.Name, &base.Description, &base.CreatedAt, &base.UpdatedAt); err != nil {
			return nil, err
		}
		bases = append(bases, base)
	}
	return bases, rows.Err()
}

// GetKnowledgeBase retrieves a single knowledge base by ID.
func (db *Database) GetKnowledgeBase(id int64) (*KnowledgeBase, error) {
	var base KnowledgeBase
	err := db.conn.QueryRow(
		`SELECT id, name, description, created_at, updated_at FROM knowledge_bases WHERE id = ?`, id,
	).Scan(&base.ID, &base.Name, &base.Description, &base.CreatedAt, &base.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &base, nil
}

// UpdateKnowledgeBase updates an existing knowledge base.
func (db *Database) UpdateKnowledgeBase(base *KnowledgeBase) error {
	now := time.Now()
	res, err := db.conn.Exec(
		`UPDATE knowledge_bases SET name = ?, description = ?, updated_at = ? WHERE id = ?`,
		base.Name, base.Description, now, base.ID,
	)
	if err != nil {
		return err
	}
	if err := errNoRowsWhenUnchanged(res); err != nil {
		return err
	}
	base.UpdatedAt = now
	return nil
}

// DeleteKnowledgeBase removes a knowledge base and cascades its documents and chunks.
func (db *Database) DeleteKnowledgeBase(id int64) error {
	tx, err := db.conn.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(`DELETE FROM knowledge_chunks_fts WHERE knowledge_base_id = ?`, id); err != nil {
		return err
	}
	res, err := tx.Exec(`DELETE FROM knowledge_bases WHERE id = ?`, id)
	if err != nil {
		return err
	}
	if err := errNoRowsWhenUnchanged(res); err != nil {
		return err
	}
	return tx.Commit()
}

// CreateKnowledgeDocument inserts a document and refreshes searchable chunks.
func (db *Database) CreateKnowledgeDocument(doc *KnowledgeDocument) error {
	tx, err := db.conn.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	tagsJSON, err := marshalKnowledgeTags(doc.Tags)
	if err != nil {
		return err
	}
	doc.SourceType = defaultKnowledgeSourceType(doc.SourceType)
	now := time.Now()
	res, err := tx.Exec(
		`INSERT INTO knowledge_documents (knowledge_base_id, title, content, tags, source_type, source_name, created_at, updated_at)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		doc.KnowledgeBaseID, doc.Title, doc.Content, tagsJSON, doc.SourceType, doc.SourceName, now, now,
	)
	if err != nil {
		return err
	}
	doc.ID, _ = res.LastInsertId()
	doc.CreatedAt = now
	doc.UpdatedAt = now
	if err := refreshKnowledgeChunks(tx, doc.ID, doc.KnowledgeBaseID, doc.Content); err != nil {
		return err
	}
	return tx.Commit()
}

// ListKnowledgeDocuments lists documents with optional base and text filters.
func (db *Database) ListKnowledgeDocuments(filter KnowledgeDocumentFilter) ([]KnowledgeDocument, error) {
	query := `SELECT id, knowledge_base_id, title, content, tags, source_type, source_name, created_at, updated_at FROM knowledge_documents`
	var args []interface{}
	var where []string
	if filter.KnowledgeBaseID > 0 {
		where = append(where, "knowledge_base_id = ?")
		args = append(args, filter.KnowledgeBaseID)
	}
	if q := strings.TrimSpace(filter.Query); q != "" {
		where = append(where, "(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
		like := "%" + q + "%"
		args = append(args, like, like, like)
	}
	if len(where) > 0 {
		query += " WHERE " + strings.Join(where, " AND ")
	}
	query += ` ORDER BY updated_at DESC, id DESC`

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var docs []KnowledgeDocument
	for rows.Next() {
		doc, err := scanKnowledgeDocument(rows)
		if err != nil {
			return nil, err
		}
		docs = append(docs, *doc)
	}
	return docs, rows.Err()
}

// GetKnowledgeDocument retrieves a single document by ID.
func (db *Database) GetKnowledgeDocument(id int64) (*KnowledgeDocument, error) {
	row := db.conn.QueryRow(
		`SELECT id, knowledge_base_id, title, content, tags, source_type, source_name, created_at, updated_at FROM knowledge_documents WHERE id = ?`, id,
	)
	return scanKnowledgeDocument(row)
}

// UpdateKnowledgeDocument updates a document and refreshes searchable chunks.
func (db *Database) UpdateKnowledgeDocument(doc *KnowledgeDocument) error {
	tx, err := db.conn.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	tagsJSON, err := marshalKnowledgeTags(doc.Tags)
	if err != nil {
		return err
	}
	doc.SourceType = defaultKnowledgeSourceType(doc.SourceType)
	now := time.Now()
	res, err := tx.Exec(
		`UPDATE knowledge_documents SET knowledge_base_id = ?, title = ?, content = ?, tags = ?, source_type = ?, source_name = ?, updated_at = ? WHERE id = ?`,
		doc.KnowledgeBaseID, doc.Title, doc.Content, tagsJSON, doc.SourceType, doc.SourceName, now, doc.ID,
	)
	if err != nil {
		return err
	}
	if err := errNoRowsWhenUnchanged(res); err != nil {
		return err
	}
	if err := refreshKnowledgeChunks(tx, doc.ID, doc.KnowledgeBaseID, doc.Content); err != nil {
		return err
	}
	doc.UpdatedAt = now
	return tx.Commit()
}

// DeleteKnowledgeDocument removes a document and its FTS rows.
func (db *Database) DeleteKnowledgeDocument(id int64) error {
	tx, err := db.conn.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(`DELETE FROM knowledge_chunks_fts WHERE document_id = ?`, id); err != nil {
		return err
	}
	res, err := tx.Exec(`DELETE FROM knowledge_documents WHERE id = ?`, id)
	if err != nil {
		return err
	}
	if err := errNoRowsWhenUnchanged(res); err != nil {
		return err
	}
	return tx.Commit()
}

// SearchKnowledge searches knowledge chunks through SQLite FTS.
func (db *Database) SearchKnowledge(filter KnowledgeSearchFilter) ([]KnowledgeSearchResult, error) {
	queryText := strings.TrimSpace(filter.Query)
	if queryText == "" {
		return []KnowledgeSearchResult{}, nil
	}
	limit := filter.Limit
	if limit <= 0 {
		limit = defaultKnowledgeLimit
	}
	if limit > maxKnowledgeLimit {
		limit = maxKnowledgeLimit
	}

	query := `SELECT f.knowledge_base_id, b.name, f.document_id, d.title, f.chunk_id,
			snippet(knowledge_chunks_fts, 3, '', '', '...', 20), bm25(knowledge_chunks_fts) AS score
		FROM knowledge_chunks_fts f
		JOIN knowledge_documents d ON d.id = f.document_id
		JOIN knowledge_bases b ON b.id = f.knowledge_base_id
		WHERE knowledge_chunks_fts MATCH ?`
	args := []interface{}{buildKnowledgeFTSQuery(queryText)}
	if filter.KnowledgeBaseID > 0 {
		query += ` AND f.knowledge_base_id = ?`
		args = append(args, filter.KnowledgeBaseID)
	}
	query += ` ORDER BY score ASC LIMIT ?`
	args = append(args, limit)

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []KnowledgeSearchResult
	for rows.Next() {
		var result KnowledgeSearchResult
		if err := rows.Scan(&result.KnowledgeBaseID, &result.KnowledgeBaseName, &result.DocumentID, &result.DocumentTitle, &result.ChunkID, &result.Snippet, &result.Score); err != nil {
			return nil, err
		}
		results = append(results, result)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(results) > 0 {
		return results, nil
	}
	return db.searchKnowledgeByText(filter, queryText, limit)
}

type knowledgeDocumentScanner interface {
	Scan(dest ...interface{}) error
}

func scanKnowledgeDocument(scanner knowledgeDocumentScanner) (*KnowledgeDocument, error) {
	var doc KnowledgeDocument
	var tagsJSON string
	if err := scanner.Scan(&doc.ID, &doc.KnowledgeBaseID, &doc.Title, &doc.Content, &tagsJSON, &doc.SourceType, &doc.SourceName, &doc.CreatedAt, &doc.UpdatedAt); err != nil {
		return nil, err
	}
	if tagsJSON != "" {
		if err := json.Unmarshal([]byte(tagsJSON), &doc.Tags); err != nil {
			return nil, err
		}
	}
	return &doc, nil
}

func marshalKnowledgeTags(tags []string) (string, error) {
	if tags == nil {
		tags = []string{}
	}
	data, err := json.Marshal(tags)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func defaultKnowledgeSourceType(sourceType string) string {
	if strings.TrimSpace(sourceType) == "" {
		return KnowledgeSourceManual
	}
	return sourceType
}

func refreshKnowledgeChunks(tx *sql.Tx, documentID, knowledgeBaseID int64, content string) error {
	if _, err := tx.Exec(`DELETE FROM knowledge_chunks_fts WHERE document_id = ?`, documentID); err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM knowledge_chunks WHERE document_id = ?`, documentID); err != nil {
		return err
	}
	for i, chunk := range chunkKnowledgeContent(content) {
		res, err := tx.Exec(
			`INSERT INTO knowledge_chunks (document_id, knowledge_base_id, chunk_index, content) VALUES (?, ?, ?, ?)`,
			documentID, knowledgeBaseID, i, chunk,
		)
		if err != nil {
			return err
		}
		chunkID, _ := res.LastInsertId()
		if _, err := tx.Exec(
			`INSERT INTO knowledge_chunks_fts (chunk_id, document_id, knowledge_base_id, content) VALUES (?, ?, ?, ?)`,
			chunkID, documentID, knowledgeBaseID, chunk,
		); err != nil {
			return err
		}
	}
	return nil
}

func chunkKnowledgeContent(content string) []string {
	paragraphs := splitKnowledgeParagraphs(strings.TrimSpace(content))
	if len(paragraphs) == 0 {
		return nil
	}
	paragraphs = mergeShortKnowledgeParagraphs(paragraphs)

	var chunks []string
	for _, paragraph := range paragraphs {
		chunks = append(chunks, splitLongKnowledgeChunk(paragraph, maxChunkRunes)...)
	}
	return chunks
}

func splitKnowledgeParagraphs(content string) []string {
	var paragraphs []string
	var current []string
	for _, line := range strings.Split(content, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			if len(current) > 0 {
				paragraphs = append(paragraphs, strings.Join(current, "\n"))
				current = nil
			}
			continue
		}
		current = append(current, line)
	}
	if len(current) > 0 {
		paragraphs = append(paragraphs, strings.Join(current, "\n"))
	}
	return paragraphs
}

func mergeShortKnowledgeParagraphs(paragraphs []string) []string {
	var merged []string
	for _, paragraph := range paragraphs {
		paragraph = strings.TrimSpace(paragraph)
		if paragraph == "" {
			continue
		}
		if len(merged) > 0 && runeLen(merged[len(merged)-1]) < minChunkRunes && runeLen(merged[len(merged)-1])+runeLen(paragraph)+2 <= maxChunkRunes {
			merged[len(merged)-1] += "\n\n" + paragraph
			continue
		}
		merged = append(merged, paragraph)
	}
	return merged
}

func splitLongKnowledgeChunk(content string, maxRunes int) []string {
	runes := []rune(strings.TrimSpace(content))
	if len(runes) <= maxRunes {
		return []string{string(runes)}
	}

	var chunks []string
	for len(runes) > maxRunes {
		cut := maxRunes
		for cut > maxRunes/2 && !unicode.IsSpace(runes[cut-1]) {
			cut--
		}
		if cut <= maxRunes/2 {
			cut = maxRunes
		}
		chunk := strings.TrimSpace(string(runes[:cut]))
		if chunk != "" {
			chunks = append(chunks, chunk)
		}
		runes = []rune(strings.TrimSpace(string(runes[cut:])))
	}
	if len(runes) > 0 {
		chunks = append(chunks, string(runes))
	}
	return chunks
}

func runeLen(s string) int {
	return len([]rune(s))
}

func buildKnowledgeFTSQuery(query string) string {
	var terms []string
	for _, field := range strings.Fields(query) {
		field = strings.ReplaceAll(field, `"`, `""`)
		if field != "" {
			terms = append(terms, `"`+field+`"`)
		}
	}
	if len(terms) == 0 {
		return `""`
	}
	return strings.Join(terms, " ")
}

func (db *Database) searchKnowledgeByText(filter KnowledgeSearchFilter, queryText string, limit int) ([]KnowledgeSearchResult, error) {
	patterns := buildKnowledgeLikePatterns(queryText)
	if len(patterns) == 0 {
		return []KnowledgeSearchResult{}, nil
	}

	var clauses []string
	var args []interface{}
	for _, pattern := range patterns {
		clauses = append(clauses, "(c.content LIKE ? OR d.title LIKE ?)")
		like := "%" + pattern + "%"
		args = append(args, like, like)
	}

	query := `SELECT c.knowledge_base_id, b.name, c.document_id, d.title, c.id, c.content, 0.0 AS score
		FROM knowledge_chunks c
		JOIN knowledge_documents d ON d.id = c.document_id
		JOIN knowledge_bases b ON b.id = c.knowledge_base_id
		WHERE (` + strings.Join(clauses, " OR ") + `)`
	if filter.KnowledgeBaseID > 0 {
		query += ` AND c.knowledge_base_id = ?`
		args = append(args, filter.KnowledgeBaseID)
	}
	query += ` ORDER BY d.updated_at DESC, c.chunk_index ASC LIMIT ?`
	args = append(args, limit)

	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var results []KnowledgeSearchResult
	for rows.Next() {
		var result KnowledgeSearchResult
		if err := rows.Scan(&result.KnowledgeBaseID, &result.KnowledgeBaseName, &result.DocumentID, &result.DocumentTitle, &result.ChunkID, &result.Snippet, &result.Score); err != nil {
			return nil, err
		}
		results = append(results, result)
	}
	return results, rows.Err()
}

func buildKnowledgeLikePatterns(query string) []string {
	seen := map[string]bool{}
	var patterns []string
	add := func(pattern string) {
		pattern = strings.TrimSpace(pattern)
		if pattern == "" || seen[pattern] {
			return
		}
		seen[pattern] = true
		patterns = append(patterns, pattern)
	}

	add(query)
	for _, field := range strings.Fields(query) {
		add(field)
	}
	for _, segment := range cjkSegments(query) {
		runes := []rune(segment)
		for width := minInt(8, len(runes)); width >= 2; width-- {
			for start := 0; start+width <= len(runes); start++ {
				add(string(runes[start : start+width]))
				if len(patterns) >= 24 {
					return patterns
				}
			}
		}
	}
	return patterns
}

func cjkSegments(s string) []string {
	var segments []string
	var current []rune
	flush := func() {
		if len(current) > 0 {
			segments = append(segments, string(current))
			current = nil
		}
	}
	for _, r := range s {
		if unicode.Is(unicode.Han, r) {
			current = append(current, r)
			continue
		}
		flush()
	}
	flush()
	return segments
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
