package db

import "time"

// Conversation is a chat session with the AI assistant.
type Conversation struct {
	ID        int64     `json:"id"`
	Title     string    `json:"title"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

// ChatMessage is a single turn in a conversation. ToolCalls holds a JSON array
// (assistant turns that request tools); ToolCallID links a tool-result turn back
// to the call that produced it. Both are empty strings when unused.
type ChatMessage struct {
	ID             int64     `json:"id"`
	ConversationID int64     `json:"conversation_id"`
	Role           string    `json:"role"` // user | assistant | tool
	Content        string    `json:"content"`
	ToolCalls      string    `json:"tool_calls,omitempty"`
	ToolCallID     string    `json:"tool_call_id,omitempty"`
	ProviderBlocks string    `json:"provider_blocks,omitempty"`
	CreatedAt      time.Time `json:"created_at"`
}

// CreateConversation inserts a new conversation and returns it with its ID set.
func (db *Database) CreateConversation(title string) (*Conversation, error) {
	if title == "" {
		title = "新对话"
	}
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)`,
		title, now, now,
	)
	if err != nil {
		return nil, err
	}
	id, _ := res.LastInsertId()
	return &Conversation{ID: id, Title: title, CreatedAt: now, UpdatedAt: now}, nil
}

// ListConversations returns all conversations, most recently updated first.
func (db *Database) ListConversations() ([]Conversation, error) {
	rows, err := db.conn.Query(
		`SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Conversation
	for rows.Next() {
		var c Conversation
		if err := rows.Scan(&c.ID, &c.Title, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}

// AppendMessage stores one message and bumps the conversation's updated_at.
func (db *Database) AppendMessage(m *ChatMessage) error {
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO chat_messages (conversation_id, role, content, tool_calls, tool_call_id, provider_blocks, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?)`,
		m.ConversationID, m.Role, m.Content, m.ToolCalls, m.ToolCallID, m.ProviderBlocks, now,
	)
	if err != nil {
		return err
	}
	m.ID, _ = res.LastInsertId()
	m.CreatedAt = now
	_, _ = db.conn.Exec(`UPDATE conversations SET updated_at = ? WHERE id = ?`, now, m.ConversationID)
	return nil
}

// ListMessages returns all messages in a conversation, oldest first.
func (db *Database) ListMessages(convID int64) ([]ChatMessage, error) {
	rows, err := db.conn.Query(
		`SELECT id, conversation_id, role, content, tool_calls, tool_call_id, provider_blocks, created_at
		 FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC`, convID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []ChatMessage
	for rows.Next() {
		var m ChatMessage
		if err := rows.Scan(&m.ID, &m.ConversationID, &m.Role, &m.Content, &m.ToolCalls, &m.ToolCallID, &m.ProviderBlocks, &m.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, nil
}

// DeleteConversation removes a conversation and its messages.
func (db *Database) DeleteConversation(id int64) error {
	if _, err := db.conn.Exec(`DELETE FROM chat_messages WHERE conversation_id = ?`, id); err != nil {
		return err
	}
	_, err := db.conn.Exec(`DELETE FROM conversations WHERE id = ?`, id)
	return err
}
